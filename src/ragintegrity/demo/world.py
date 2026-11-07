"""A self-contained synthetic RAG deployment with *known* injected faults.

``DemoWorld`` holds an in-memory source bucket, processing manifest and vector index. Because the
faults are injected on purpose, ``world.faults`` is a ground truth the test-suite compares the
engine's findings against. The same world powers ``RAGI_MODE=demo`` and ``scripts/seed_live.py``.
"""

from __future__ import annotations

import hashlib
import random
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..connectors.payload import build_payload_map, payload_to_chunk
from ..models import (
    ChunkRow,
    ConnectionStatus,
    DocKey,
    Fingerprint,
    IndexedChunk,
    IssueType,
    ManifestRow,
    Scope,
    SourceDoc,
    sha256_hex,
)
from .pipeline import build_points, make_text

COLLECTION = "kb_main"
TENANTS = ("acme", "globex", "initech")
CATEGORIES = ("policies", "runbooks", "contracts", "product", "support")

TARGET_FP = Fingerprint(
    parser_version="parser-2.1", chunking_version="recursive-v2", chunk_size=400, chunk_overlap=40,
    embedding_model="demo-embed-v2", embedding_dim=16, preprocessing="clean-v1",
)
OLD_FP = Fingerprint(
    parser_version="parser-1.4", chunking_version="fixed-v1", chunk_size=600, chunk_overlap=0,
    embedding_model="demo-embed-v1", embedding_dim=16, preprocessing="clean-v1",
)

# (fault name, how many documents)
FAULT_PLAN = (
    ("never_embedded", 5), ("false_success", 3), ("stale", 7), ("deleted_with_manifest", 2),
    ("deleted_no_manifest", 3), ("partial", 4), ("duplicate", 3), ("acl_mismatch", 2), ("count_mismatch", 2),
    ("drift", 10), ("superseded", 3), ("empty_embedding", 2), ("tenant_mismatch", 1),
)
EXPECTED_TYPES = {
    "never_embedded": [IssueType.MISSING_EMBEDDING],
    "false_success": [IssueType.MISSING_EMBEDDING],
    "stale": [IssueType.STALE_EMBEDDING],
    "deleted_with_manifest": [IssueType.ORPHAN_VECTOR],
    "deleted_no_manifest": [IssueType.ORPHAN_VECTOR],
    "partial": [IssueType.PARTIAL_INDEX],
    "duplicate": [IssueType.DUPLICATE_CHUNK],
    "acl_mismatch": [IssueType.METADATA_INCONSISTENT],
    "count_mismatch": [IssueType.METADATA_INCONSISTENT],
    "drift": [IssueType.PIPELINE_DRIFT],
    "superseded": [IssueType.SUPERSEDED_ACTIVE],
    "empty_embedding": [IssueType.EMPTY_EMBEDDING],
    "tenant_mismatch": [IssueType.TENANT_MISMATCH],  # plus MISSING_EMBEDDING for the real document
}


@dataclass
class StoredPoint:
    collection: str
    payload: dict[str, Any]
    vector: list[float]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def etag_of(text: str) -> str:
    """What S3 reports as the ETag of a single-part upload of ``text`` (so a seeded bucket agrees with the world)."""
    return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()


class DemoWorld:
    def __init__(
        self,
        seed: int = 7,
        docs_per_tenant: int = 80,
        tenants: tuple[str, ...] = TENANTS,
        now: datetime | None = None,
        faults: bool = True,
    ) -> None:
        self.rng = random.Random(seed)
        self.now = now or datetime.now(timezone.utc)
        self.tenants = tenants
        self.sources: dict[DocKey, SourceDoc] = {}
        self.manifest: dict[DocKey, ManifestRow] = {}
        self.chunk_manifest: dict[DocKey, dict[str, ChunkRow]] = {}
        self.points: dict[str, StoredPoint] = {}
        self.versions: dict[DocKey, int] = {}
        self.faults: dict[DocKey, dict[str, Any]] = {}  # key -> {"fault": name, "types": [...]}
        self.flaky: dict[DocKey, int] = {}  # worker "succeeds" but writes half the chunks N times
        self.query_log: list[dict[str, Any]] = []
        self.worker_calls: list[dict[str, Any]] = []
        self._category: dict[DocKey, str] = {}
        self._build(docs_per_tenant, faults)

    # ------------------------------------------------------------------ construction
    def _acl(self, key: DocKey) -> str:
        return sha256_hex(f"acl:{key[0]}:{self._category[key]}")[:16]

    def _build(self, docs_per_tenant: int, faults: bool) -> None:
        n = 0
        for tenant in self.tenants:
            for _ in range(docs_per_tenant):
                n += 1
                cat = self.rng.choice(CATEGORIES)
                doc_id = f"{cat}/{self.rng.choice(['alpha', 'bravo', 'delta', 'omega', 'sigma', 'zenith'])}-{n:03d}.md"
                key = (tenant, doc_id)
                self._category[key] = cat
                self.versions[key] = self.rng.randint(1, 3)
                self._refresh_source(key, modified=self.now - timedelta(days=self.rng.randint(3, 120)))
                self._index(key, TARGET_FP)
        if faults:
            self._inject_faults()
        self._build_query_log()

    def _refresh_source(self, key: DocKey, modified: datetime) -> None:
        tenant, doc_id = key
        text = make_text(doc_id, self.versions[key])
        h = sha256_hex(text)
        self.sources[key] = SourceDoc(
            tenant_id=tenant, document_id=doc_id, source_uri=f"s3://demo-bucket/{tenant}/{doc_id}",
            source_version=etag_of(text), source_hash=h, hash_reliable=True,
            size_bytes=self.rng.randint(40_000, 900_000), last_modified=_iso(modified),
        )

    def _index(self, key: DocKey, fp: Fingerprint, *, write_manifest: bool = True, version: int | None = None) -> list[str]:
        """Index the doc at ``version`` (default: current) and record the manifest row."""
        tenant, doc_id = key
        version = version or self.versions[key]
        text = make_text(doc_id, version)
        h = sha256_hex(text)
        sv = etag_of(text)
        pts, rows = build_points(tenant, doc_id, text, source_hash=h, source_version=sv, fp=fp, acl_hash=self._acl(key))
        for p in pts:
            self.points[p.point_id] = StoredPoint(COLLECTION, p.payload, p.vector)
        if write_manifest:
            src = self.sources.get(key)
            updated = (parse_iso(src.last_modified) if src and src.last_modified else self.now) + timedelta(minutes=5)
            self.manifest[key] = ManifestRow(
                tenant_id=tenant, document_id=doc_id, source_uri=f"s3://demo-bucket/{tenant}/{doc_id}",
                source_version=sv, source_hash=h, parsed_hash=sha256_hex("parsed:" + text), fingerprint=fp,
                expected_chunk_count=len(rows), indexed_chunk_count=len(rows), indexed_version=sv,
                processing_status="success", last_verified_at=None, updated_at=_iso(updated), acl_hash=self._acl(key),
            )
            self.chunk_manifest[key] = {r.chunk_id: r for r in rows}
        return [p.point_id for p in pts]

    def points_of(self, key: DocKey) -> list[str]:
        return [pid for pid, sp in self.points.items()
                if sp.payload.get("tenant_id") == key[0] and sp.payload.get("document_id") == key[1]]

    def _inject_faults(self) -> None:
        pool = sorted(self.sources)
        self.rng.shuffle(pool)
        cursor = 0

        def take(count: int) -> list[DocKey]:
            nonlocal cursor
            chosen = pool[cursor : cursor + count]
            cursor += count
            return chosen

        for name, count in FAULT_PLAN:
            for key in take(count):
                getattr(self, f"_fault_{name}")(key)
                types = [t.value for t in EXPECTED_TYPES[name]]
                if name == "tenant_mismatch":
                    self.faults[key] = {"fault": "tenant_mismatch_source", "types": [IssueType.MISSING_EMBEDDING.value]}
                    self.faults[self._mismatch_key] = {"fault": name, "types": types}
                else:
                    self.faults[key] = {"fault": name, "types": types}

    def _drop_points(self, key: DocKey) -> None:
        for pid in self.points_of(key):
            del self.points[pid]

    def _fault_never_embedded(self, key: DocKey) -> None:
        self._drop_points(key)
        self.manifest.pop(key, None)
        self.chunk_manifest.pop(key, None)

    def _fault_false_success(self, key: DocKey) -> None:
        self._drop_points(key)  # manifest still says success with N indexed chunks

    def _fault_stale(self, key: DocKey) -> None:
        self.versions[key] += 1  # the source moves on; manifest and index stay behind
        self._refresh_source(key, modified=self.now - timedelta(days=1))

    def _fault_deleted_with_manifest(self, key: DocKey) -> None:
        del self.sources[key]

    def _fault_deleted_no_manifest(self, key: DocKey) -> None:
        del self.sources[key]
        self.manifest.pop(key, None)
        self.chunk_manifest.pop(key, None)

    def _fault_partial(self, key: DocKey) -> None:
        pids = self.points_of(key)
        for pid in pids[len(pids) // 2 :]:  # the ingest worker died half way; manifest still claims all
            del self.points[pid]

    def _fault_duplicate(self, key: DocKey) -> None:
        for pid in self.points_of(key)[:2]:  # a retried job re-inserted chunks with fresh ids
            sp = self.points[pid]
            self.points[str(uuid.UUID(int=self.rng.getrandbits(128), version=4))] = StoredPoint(
                sp.collection, dict(sp.payload), list(sp.vector))

    def _fault_acl_mismatch(self, key: DocKey) -> None:
        self.manifest[key].acl_hash = sha256_hex("acl:changed")[:16]

    def _fault_count_mismatch(self, key: DocKey) -> None:
        self.manifest[key].indexed_chunk_count = (self.manifest[key].indexed_chunk_count or 0) + 1

    def _fault_drift(self, key: DocKey) -> None:
        self._drop_points(key)
        self._index(key, OLD_FP)

    def _fault_superseded(self, key: DocKey) -> None:
        # the doc was updated and re-indexed correctly, but the previous version's vectors were never removed
        old_version = self.versions[key]
        self._drop_points(key)
        self._index(key, TARGET_FP, write_manifest=False, version=old_version)
        self.versions[key] += 1
        self._refresh_source(key, modified=self.now - timedelta(days=2))
        self._index(key, TARGET_FP)

    def _fault_empty_embedding(self, key: DocKey) -> None:
        for pid in self.points_of(key)[:2]:
            self.points[pid].vector = [0.0] * len(self.points[pid].vector)

    def _fault_tenant_mismatch(self, key: DocKey) -> None:
        other = next(t for t in self.tenants if t != key[0])
        for pid in self.points_of(key):
            self.points[pid].payload["tenant_id"] = other
        self._mismatch_key = (other, key[1])

    def _build_query_log(self) -> None:
        by_tenant: dict[str, list[str]] = {}
        for t, d in self.sources:
            by_tenant.setdefault(t, []).append(d)
        for tenant, docs in by_tenant.items():
            weights = [1.0 / (i + 1) for i in range(len(docs))]  # a few documents attract most queries
            order = docs[:]
            self.rng.shuffle(order)
            for i in range(300):
                picked = self.rng.choices(order, weights=weights, k=self.rng.randint(2, 4))
                self.query_log.append({
                    "ts": _iso(self.now - timedelta(hours=self.rng.randint(1, 24 * 14))),
                    "tenant_id": tenant, "query_hash": sha256_hex(f"{tenant}:{i}")[:12],
                    "retrieved_doc_ids": sorted(set(picked)),
                })

    # ------------------------------------------------------------------ customer repair worker (in-process)
    def run_worker(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Stand-in for the customer's ingestion worker, behind the repair webhook."""
        self.worker_calls.append({"event": payload.get("event"), "phase": payload.get("phase")})
        phase = payload.get("phase")
        done = 0
        if phase == "reindex":
            for item in payload.get("items", []):
                key = (item["tenant_id"], item["document_id"])
                actions = item.get("actions") or [item.get("action")]
                if key not in self.sources:
                    continue
                if "reindex_full" in actions or "reindex_chunks" in actions:
                    self._worker_reindex(key)
                    done += 1
                if "fix_metadata" in actions:
                    self._worker_fix_metadata(key)
                    done += 1
        elif phase == "cleanup":
            for group in payload.get("cleanup", []):
                for pid in group.get("point_ids", []):
                    if self.points.pop(pid, None) is not None:
                        done += 1
                key = (group["tenant_id"], group["document_id"])
                if key not in self.sources and not self.points_of(key):
                    # a deleted document: also retire its manifest row so the pipeline's books are clean
                    self.manifest.pop(key, None)
                    self.chunk_manifest.pop(key, None)
        return {"accepted": True, "processed": done}

    def _worker_reindex(self, key: DocKey) -> None:
        src = self.sources[key]
        text = make_text(key[1], self.versions[key])
        pts, rows = build_points(key[0], key[1], text, source_hash=src.source_hash or "", source_version=src.source_version or "",
                                 fp=TARGET_FP, acl_hash=self._acl(key))
        flaky = self.flaky.get(key, 0) > 0
        if flaky:
            self.flaky[key] -= 1
        for p in pts[: max(1, len(pts) // 2)] if flaky else pts:  # flaky = reports success, writes half
            self.points[p.point_id] = StoredPoint(COLLECTION, p.payload, p.vector)
        self.manifest[key] = ManifestRow(
            tenant_id=key[0], document_id=key[1], source_uri=src.source_uri, source_version=src.source_version,
            source_hash=src.source_hash, parsed_hash=sha256_hex("parsed:" + text), fingerprint=TARGET_FP,
            expected_chunk_count=len(rows), indexed_chunk_count=len(rows), indexed_version=src.source_version,
            processing_status="success", updated_at=_iso(self.now), acl_hash=self._acl(key),
        )
        self.chunk_manifest[key] = {r.chunk_id: r for r in rows}

    def _worker_fix_metadata(self, key: DocKey) -> None:
        m = self.manifest.get(key)
        if not m:
            return
        live = [sp for pid in self.points_of(key) if (sp := self.points[pid]).payload.get("source_hash") == self.sources[key].source_hash]
        m.indexed_chunk_count = len({sp.payload.get("chunk_id") for sp in live})
        m.acl_hash = self._acl(key)
        m.source_hash = self.sources[key].source_hash
        m.indexed_version = self.sources[key].source_version


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------------------------- #
# In-memory connectors over a DemoWorld


class DemoSource:
    def __init__(self, world: DemoWorld) -> None:
        self.world = world

    def inventory(self, scope: Scope | None = None) -> Iterator[SourceDoc]:
        for key, doc in list(self.world.sources.items()):
            if scope is None or scope.matches(key):
                yield doc

    def health(self) -> ConnectionStatus:
        return ConnectionStatus("S3 source (demo)", "s3", True, f"{len(self.world.sources)} objects in demo bucket")


class DemoManifest:
    has_chunk_manifest = True

    def __init__(self, world: DemoWorld) -> None:
        self.world = world

    def documents(self, scope: Scope | None = None) -> Iterator[ManifestRow]:
        for key, row in list(self.world.manifest.items()):
            if scope is None or scope.matches(key):
                yield row

    def chunks(self, scope: Scope | None = None) -> Iterator[ChunkRow]:
        for key, rows in list(self.world.chunk_manifest.items()):
            if scope is None or scope.matches(key):
                yield from rows.values()

    def health(self) -> ConnectionStatus:
        return ConnectionStatus("Manifest (demo)", "postgres", True, f"{len(self.world.manifest)} manifest rows")


class DemoIndex:
    def __init__(self, world: DemoWorld, collection: str = COLLECTION) -> None:
        self.world = world
        self.collection = collection
        self.pmap = build_payload_map(None)

    def collections(self) -> list[str]:
        return [self.collection]

    def vector_sizes(self) -> dict[str, int | None]:
        return {self.collection: TARGET_FP.embedding_dim}

    def scan(self, scope: Scope | None = None, with_vectors: bool = False) -> Iterator[IndexedChunk]:
        for pid, sp in list(self.world.points.items()):
            tenant = sp.payload.get("tenant_id")
            doc = sp.payload.get("document_id")
            if scope is not None and not scope.is_full:
                if tenant is None or doc is None or not scope.matches((tenant, doc)):
                    continue
            yield payload_to_chunk(sp.collection, pid, sp.payload, self.pmap, vector=sp.vector, check_vector=with_vectors)

    def probe(
        self, collection: str, point_id: str, tenant_id: str | None, top_k: int
    ) -> list[tuple[str, float, str | None]] | None:
        target = self.world.points.get(point_id)
        if target is None:
            return None
        q = target.vector
        scored = []
        for pid, sp in self.world.points.items():
            if tenant_id is not None and sp.payload.get("tenant_id") != tenant_id:
                continue
            scored.append((pid, sum(a * b for a, b in zip(q, sp.vector, strict=False)), sp.payload.get("document_id")))
        scored.sort(key=lambda t: -t[1])
        return scored[:top_k]

    def health(self) -> ConnectionStatus:
        return ConnectionStatus("Vector index (demo)", "qdrant", True, f"{len(self.world.points)} points in '{self.collection}'")
