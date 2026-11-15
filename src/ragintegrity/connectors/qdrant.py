"""Read-only Qdrant vector inventory.

Uses ``scroll`` (payload only; vectors only when asked) so memory stays flat regardless of
collection size, and ``retrieve`` + ``query_points`` for retrieval probes. Nothing is ever written
or deleted by this connector.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from ..config import Settings
from ..ids import number_form
from ..models import ConnectionStatus, IndexedChunk, Scope
from .base import ConnectorError, ScanStats, check_deadline
from .payload import _dig, build_payload_map, payload_to_chunk
from .resilience import call_with_retry

FILTER_BATCH = 5000  # document ids per server-side filter (each batch is one scroll pass over the collection)


def _coerce_id(point_id: str) -> Any:
    return int(point_id) if point_id.isdigit() else point_id


def _explain_qdrant(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "index required" in low:
        return ("Qdrant needs a payload index on the field used to filter by document (strict mode). Ask the cluster owner to create a "
                "keyword index on it, or turn off 'Only audit documents found in the source (S3)'.")
    if "403" in msg or "forbidden" in low or "401" in msg or "unauthorized" in low:
        return "Qdrant rejected the API key (a read-capable key is required)."
    if "timed out" in low or "timeout" in low:
        return ("Qdrant timed out. Check the URL and port (Qdrant Cloud uses https://<cluster>:6333). On a very large collection, "
                "filtering by a field that has no payload index is slow: ask the cluster owner to create a keyword index on the "
                "document id field (for example source_id).")
    if "name or service not known" in low or "getaddrinfo" in low or "nodename nor servname" in low:
        return "The host name could not be resolved."
    if "connection refused" in low or "connecterror" in low:
        return "Connection refused: check the URL and port."
    if "not found" in low or "doesn't exist" in low:
        return "Not found: check the collection name."
    return f"{type(exc).__name__}: {msg[:160]}"


def _is_rejection(exc: Exception) -> bool:
    """Qdrant refused the request itself (a 400, for example "index required"), as opposed to being slow or unreachable."""
    return getattr(exc, "status_code", None) == 400 or "bad request" in str(exc).lower()


def client_timeout(settings: Settings, fast: bool) -> int:
    """Seconds one Qdrant request may take. Under a time budget (serverless) a single slow request must fail with a clear
    message well before the platform kills the whole function, which would leave the run marked 'running' forever."""
    if fast:
        return 8
    limit = settings.audit_seconds_limit
    return max(10, min(60, limit - 20)) if limit else 60


class QdrantIndex:
    def __init__(self, settings: Settings, client: Any = None, fast: bool = False) -> None:
        """``fast`` is for diagnostics: give up on an unreachable server within seconds."""
        self.s = settings
        self.pmap = build_payload_map(settings.payload_map)
        self.vector_name = settings.qdrant_vector_name
        if client is None:
            if not settings.qdrant_url:
                raise ConnectorError("RAGI_QDRANT_URL is not set")
            from qdrant_client import QdrantClient

            # check_compatibility=False: no extra round trip (and no warning) just to read the server version
            client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key,
                                  timeout=client_timeout(settings, fast), check_compatibility=False)
        self.client = client
        self._names = settings.collections
        self.deadline: float | None = None  # set by the audit: a time.monotonic() value after which scanning must stop
        self.scan_stats = ScanStats()  # shared with the engine: pages, retries, recovered and unrecoverable errors
        self.on_progress: Any = None  # called (at most every couple of seconds) with the scan stats while a scan runs
        self.retry_attempts = 4
        self._sleep = time.sleep  # replaced in tests so backoff does not slow them down
        self._last_progress = 0.0

    # --------------------------------------------------------------------------------- reliability
    def _call(self, fn: Any) -> Any:
        """One request to Qdrant, retried with backoff when the failure can pass (see resilience.py)."""
        return call_with_retry(fn, stats=self.scan_stats, deadline=self.deadline, attempts=self.retry_attempts, sleep=self._sleep)

    def estimated_points(self) -> int | None:
        """The approximate number of points in the collections being audited (one cheap request each), or None."""
        total = 0
        try:
            for name in self.collections():
                total += self._call(lambda n=name: self.client.count(collection_name=n, exact=False)).count
        except Exception:
            return None
        self.scan_stats.estimated_total = total
        return total

    def _progress(self) -> None:
        cb = self.on_progress
        if cb is None or time.monotonic() - self._last_progress < 2.0:
            return
        self._last_progress = time.monotonic()
        try:
            cb(self.scan_stats)
        except Exception:  # a progress note must never break a scan
            pass

    # --------------------------------------------------------------------------------- meta
    def collections(self) -> list[str]:
        if self._names:
            return list(self._names)
        return sorted(c.name for c in self.client.get_collections().collections)

    def vector_sizes(self) -> dict[str, int | None]:
        sizes: dict[str, int | None] = {}
        for name in self.collections():
            try:
                vectors = self.client.get_collection(name).config.params.vectors
                if isinstance(vectors, dict):
                    v = vectors.get(self.vector_name) if self.vector_name else next(iter(vectors.values()), None)
                else:
                    v = vectors
                sizes[name] = getattr(v, "size", None)
            except Exception:
                sizes[name] = None
        return sizes

    # --------------------------------------------------------------------------------- scan
    def _top_level(self, path: str) -> str:
        return path.split(".")[0]

    def _filters(self, scope: Scope | None) -> list[tuple[Any, Any]]:
        """Server-side filters for a scope, as ``(filter, text_only_filter)`` pairs. A long document list is split into batches
        (a document id is in exactly one batch).

        Qdrant keeps ``170`` and ``"170"`` apart, so a filter on text ids alone finds nothing when the index stores numbers.
        The first filter of each pair matches both forms; the second is the text-only version, used if a server refuses the
        number form."""
        if scope is None or scope.is_full:
            return [(None, None)]
        from qdrant_client import models as qm

        def either(key: str, values: list[str], many: bool) -> tuple[Any, Any]:
            text = (qm.FieldCondition(key=key, match=qm.MatchAny(any=values)) if many
                    else qm.FieldCondition(key=key, match=qm.MatchValue(value=values[0])))
            numbers = [n for n in (number_form(v) for v in values) if n is not None]
            if not numbers:
                return text, text
            number = (qm.FieldCondition(key=key, match=qm.MatchAny(any=numbers)) if many
                      else qm.FieldCondition(key=key, match=qm.MatchValue(value=numbers[0])))
            return qm.Filter(should=[text, number]), text

        both: list[Any] = []
        text_only: list[Any] = []
        if scope.tenant:
            b, t = either(self.pmap["tenant_id"], [scope.tenant], many=False)
            both.append(b)
            text_only.append(t)
        if scope.keys is None:
            return [(qm.Filter(must=both), qm.Filter(must=text_only))] if both else [(None, None)]
        docs = sorted({d for _, d in scope.keys})
        out: list[tuple[Any, Any]] = []
        for i in range(0, len(docs), FILTER_BATCH):
            b, t = either(self.pmap["document_id"], docs[i:i + FILTER_BATCH], many=True)
            out.append((qm.Filter(must=[*both, b]), qm.Filter(must=[*text_only, t])))
        return out  # no documents -> no filters -> nothing to read

    def scan(self, scope: Scope | None = None, with_vectors: bool = False) -> Iterator[IndexedChunk]:
        include = sorted({self._top_level(p) for p in self.pmap.values()})
        vectors_arg: Any = [self.vector_name] if (with_vectors and self.vector_name) else with_vectors
        collections = self.collections()
        read = 0
        text_only = False  # set once a server has refused the number form of a filter
        for flt_both, flt_text in self._filters(scope):
            for coll in collections:
                offset = None
                while True:
                    check_deadline(self.deadline, "the vector index", f" ({read:,} points so far)")  # a page can be empty of matches
                    flt = flt_text if text_only else flt_both
                    def fetch(coll: str = coll, flt: Any = flt, offset: Any = offset) -> Any:  # bound now: retries repeat THIS page
                        return self.client.scroll(
                            collection_name=coll, scroll_filter=flt, limit=self.s.qdrant_page_size, offset=offset,
                            with_payload=include, with_vectors=vectors_arg,
                        )

                    try:
                        points, offset = self._call(fetch)
                    except Exception as exc:
                        # only the very first page of a pass can be retried: nothing has been read with this filter yet
                        if offset is None and flt is not flt_text and _is_rejection(exc):
                            text_only = True
                            continue
                        raise
                    read += len(points)
                    self.scan_stats.pages += 1
                    self._progress()
                    for p in points:
                        chunk = payload_to_chunk(
                            coll, p.id, p.payload, self.pmap, vector=getattr(p, "vector", None),
                            check_vector=with_vectors, vector_name=self.vector_name,
                        )
                        if scope is not None and not scope.is_full and chunk.document_id:
                            key = (chunk.tenant_id or self.s.default_tenant, chunk.document_id)
                            if not scope.matches(key):
                                continue
                        yield chunk
                    if offset is None:
                        break

    # --------------------------------------------------------------------------------- a look at the ids (setup check)
    def id_sample(self, limit: int = 1000) -> dict[str, Any]:
        """The document and tenant ids of a random sample of points, exactly as stored (a number stays a number).

        Used by the setup check to see what the index calls its documents. Falls back to the first points of each
        collection on a server that cannot sample at random. Reads payloads only; never vectors."""
        from qdrant_client import models as qm

        names = self.collections()
        paths = {"document_id": self.pmap["document_id"], "tenant_id": self.pmap["tenant_id"]}
        revision = (self.pmap["source_hash"], self.pmap["source_version"])  # what tells a changed file from an unchanged one
        include = sorted({self._top_level(p) for p in (*paths.values(), *revision)})
        per = max(1, limit // max(1, len(names)))
        rows: list[dict[str, Any]] = []
        approx = 0
        random_sample = True
        for coll in names:
            try:
                approx += self.client.count(collection_name=coll, exact=False).count
            except Exception:
                pass
            check_deadline(self.deadline, "the vector index", " (sampling)")
            try:
                points = self.client.query_points(collection_name=coll, query=qm.SampleQuery(sample=qm.Sample.RANDOM),
                                                  limit=per, with_payload=include, with_vectors=False).points
            except Exception:  # an older server: the first points are a weaker sample, but still show the format
                random_sample = False
                points, _ = self.client.scroll(collection_name=coll, limit=per, with_payload=include, with_vectors=False)
            for p in points:
                pl = p.payload or {}
                rows.append({"collection": coll, "point_id": str(p.id),
                             "document_id": _dig(pl, paths["document_id"]), "tenant_id": _dig(pl, paths["tenant_id"]),
                             "has_revision": any(_dig(pl, r) not in (None, "") for r in revision)})
        return {"rows": rows, "random": random_sample, "approx_points": approx, "collections": names}

    # --------------------------------------------------------------------------------- probe
    def probe(
        self, collection: str, point_id: str, tenant_id: str | None, top_k: int
    ) -> list[tuple[str, float, str | None]] | None:
        tenant_field = self.pmap["tenant_id"]
        recs = self.client.retrieve(collection_name=collection, ids=[_coerce_id(point_id)], with_vectors=True,
                                    with_payload=[self._top_level(tenant_field)])
        if not recs or recs[0].vector is None:
            return None
        vec = recs[0].vector
        if isinstance(vec, dict):
            vec = vec.get(self.vector_name) if self.vector_name else next(iter(vec.values()), None)
        if not vec:
            return None
        flt = None
        # A real query is scoped to its tenant, so the probe is too, but only when the points have a tenant at all. An index whose
        # payloads carry no tenant field (a single-tenant corpus) would otherwise answer every probe with zero hits, which reads
        # as "not searchable" when nothing was searched. The point's own stored value is used, so a number stays a number.
        own = _dig(recs[0].payload or {}, tenant_field)
        if tenant_id is not None and own is not None:
            from qdrant_client import models as qm

            flt = qm.Filter(must=[qm.FieldCondition(key=tenant_field, match=qm.MatchValue(value=own))])
        res = self.client.query_points(
            collection_name=collection, query=vec, using=self.vector_name, limit=top_k, query_filter=flt,
            with_payload=[self._top_level(self.pmap["document_id"])],
        )
        out: list[tuple[str, float, str | None]] = []
        for p in res.points:
            doc = (p.payload or {}).get(self.pmap["document_id"]) if "." not in self.pmap["document_id"] else None
            out.append((str(p.id), float(p.score), doc))
        return out

    # --------------------------------------------------------------------------------- diagnostics
    def diagnose(self) -> list[dict[str, str]]:
        """Specific, actionable checks for the 'Test connection' button."""
        def chk(name: str, status: str, detail: str) -> dict[str, str]:
            return {"name": name, "status": status, "detail": detail}

        try:
            existing = sorted(c.name for c in self.client.get_collections().collections)
        except Exception as exc:
            return [chk("Qdrant reachable", "fail", _explain_qdrant(exc))]
        out = [chk("Qdrant reachable", "ok", f"{len(existing)} collection(s): {', '.join(existing[:8]) or 'none yet'}")]
        wanted = self._names or existing
        missing = [c for c in wanted if c not in existing]
        if missing:
            out.append(chk("Collections", "fail", f"not found: {', '.join(missing)}. Existing: {', '.join(existing) or 'none'}."))
            return out
        if not wanted:
            out.append(chk("Collections", "warn", "this Qdrant has no collections yet."))
            return out
        out.append(chk("Collections", "ok", f"auditing {', '.join(wanted)}"))
        for name in wanted[:5]:
            try:
                n = self.client.count(collection_name=name, exact=False).count
                size = self.vector_sizes().get(name)
                out.append(chk(f"Collection {name}", "ok" if n else "warn", f"~{n} point(s), vector size {size}" if n else "the collection is empty"))
                if not n:
                    continue
                pts, _ = self.client.scroll(collection_name=name, limit=20, with_payload=True, with_vectors=False)
                have: set[str] = set()
                for p in pts:
                    for canonical, path in self.pmap.items():
                        cur: Any = p.payload or {}
                        for part in path.split("."):
                            cur = cur.get(part) if isinstance(cur, dict) else None
                        if cur not in (None, ""):
                            have.add(canonical)
                needed = [f for f in ("document_id", "source_hash") if f not in have]
                if "document_id" not in have:
                    out.append(chk(f"Payload of {name}", "fail", "sampled points carry no document_id. Map the payload field names with the payload map."))
                elif needed:
                    out.append(chk(f"Payload of {name}", "warn", f"sampled points lack {', '.join(needed)}: freshness checks will be limited."))
                else:
                    extras = [f for f in ("tenant_id", "chunk_id", "chunk_index", "embedding_model") if f in have]
                    out.append(chk(f"Payload of {name}", "ok", f"found document_id and source_hash; also {', '.join(extras) or 'no other mapped fields'}"))
            except Exception as exc:
                out.append(chk(f"Collection {name}", "fail", _explain_qdrant(exc)))
        return out

    # --------------------------------------------------------------------------------- health
    def health(self) -> ConnectionStatus:
        t0 = time.perf_counter()
        try:
            existing = {c.name for c in self.client.get_collections().collections}
            wanted = self.collections()
            missing = [c for c in wanted if c not in existing]
            counts = {c: self.client.count(collection_name=c, exact=False).count for c in wanted if c in existing}
            ms = (time.perf_counter() - t0) * 1000
            if missing:
                return ConnectionStatus("Vector index (Qdrant)", "qdrant", False,
                                        f"collection(s) not found: {', '.join(missing)}", ms, {"counts": counts})
            return ConnectionStatus("Vector index (Qdrant)", "qdrant", True,
                                    f"{len(wanted)} collection(s), ~{sum(counts.values())} points", ms, {"counts": counts})
        except Exception as exc:
            return ConnectionStatus("Vector index (Qdrant)", "qdrant", False, f"{type(exc).__name__}: {str(exc)[:200]}")
