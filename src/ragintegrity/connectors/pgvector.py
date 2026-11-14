"""Read-only view of vectors stored in PostgreSQL with the pgvector extension (Supabase, Neon, AWS RDS and plain Postgres).

A pgvector "index" is a normal table: one row per chunk, with a vector column and some ordinary columns (or one JSON column)
that say where the chunk came from. This connector reads those rows the way the Qdrant connector reads points, and gives the
audit the same ``IndexedChunk`` objects, so every check works the same on both.

Read-only, like everything else: each page of rows is one short ``READ ONLY`` transaction with a statement timeout, and nothing
is ever written. Identifiers (schema, table, column names) are validated before they are quoted into SQL; values are always
bound parameters.

Column map. Each of our field names (document_id, source_hash, tenant_id, chunk_id, chunk_index, chunk_total, ...) points at
one of your columns, either a plain column (``"doc_id"``) or a key inside a JSON column (``"metadata.doc_id"``, the shape used by
LangChain's and LlamaIndex's tables). Two more entries say where the row id (``id``) and the vector (``vector``) are.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ..config import Settings, check_identifier
from ..ids import number_form
from ..models import ConnectionStatus, IndexedChunk, Scope
from .base import ConnectorError, ScanStats, check_deadline
from .payload import CANONICAL_FIELDS, _dig, build_payload_map, payload_to_chunk
from .postgres import _explain_pg, make_engine
from .resilience import call_with_retry

FILTER_BATCH = 5000  # document ids per server-side filter
STATEMENT_TIMEOUT = "45s"
DISTANCES = {"cosine": "<=>", "l2": "<->", "inner_product": "<#>"}
EXTRA_FIELDS = ("id", "vector")  # besides our canonical field names, the map can say where the row id and the vector are
NUMBER_TYPES = frozenset({"int2", "int4", "int8", "numeric", "float4", "float8"})
JSON_TYPES = frozenset({"json", "jsonb"})
_KEY = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def parse_path(value: str, what: str) -> tuple[str, tuple[str, ...]]:
    """``"doc_id"`` -> ("doc_id", ()); ``"metadata.doc.id"`` -> ("metadata", ("doc", "id")). Every part is checked before it can reach SQL."""
    parts = str(value).split(".")
    column = check_identifier(parts[0], f"column for {what}")
    for key in parts[1:]:
        if not _KEY.match(key):
            raise ConnectorError(f"Invalid JSON key {key!r} in the column for {what}: use letters, digits, '_' and '-' only")
    return column, tuple(parts[1:])


def build_column_map(overrides: dict[str, str] | None) -> dict[str, str]:
    """Our field name -> the column (or ``column.json.key``) that holds it. Defaults: a column with our own name; ``id`` and ``embedding``."""
    cmap = {**build_payload_map(None), "id": "id", "vector": "embedding"}
    for k, v in (overrides or {}).items():
        if k not in cmap:
            raise ConnectorError(f"Unknown column {k!r} in the column map; valid: {', '.join((*CANONICAL_FIELDS, *EXTRA_FIELDS))}")
        parse_path(v, k)
        cmap[k] = v
    return cmap


def parse_vector(value: Any) -> list[float] | None:
    """A pgvector value as the database sends it: the text ``[0.1,0.2,0.3]`` (or a list, if a driver already parsed it)."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    s = str(value).strip()
    if not (s.startswith("[") and s.endswith("]")):
        return None
    try:
        return [float(x) for x in s[1:-1].split(",")] if s[1:-1].strip() else []
    except ValueError:
        return None


class PgVectorIndex:
    label = "pgvector"

    def __init__(self, settings: Settings, engine: Engine | None = None, fast: bool = False) -> None:
        """``fast`` is for diagnostics: give up on an unreachable server within seconds."""
        self.s = settings
        if engine is None:
            if not settings.pgvector_database_url:
                raise ConnectorError("RAGI_PGVECTOR_DATABASE_URL is not set")
            engine = make_engine(settings.pgvector_database_url, null_pool=True)
        if not settings.pgvector_table:
            raise ConnectorError("RAGI_PGVECTOR_TABLE is not set")
        self.engine = engine
        self.schema = check_identifier(settings.pgvector_schema or "public", "RAGI_PGVECTOR_SCHEMA")
        self.table = check_identifier(settings.pgvector_table, "RAGI_PGVECTOR_TABLE")
        self.cmap = build_column_map(settings.pgvector_columns)
        self.pmap = {k: v for k, v in self.cmap.items() if k in CANONICAL_FIELDS}
        self.distance = (settings.pgvector_distance or "cosine").lower()
        if self.distance not in DISTANCES:
            raise ConnectorError(f"RAGI_PGVECTOR_DISTANCE must be one of {', '.join(DISTANCES)}")
        self.fast = fast
        self.deadline: float | None = None
        self.scan_stats = ScanStats()
        self.on_progress: Any = None
        self.retry_attempts = 4
        self._sleep = time.sleep
        self._last_progress = 0.0
        self._types: dict[str, str] | None = None  # column name -> pg type name (udt), read once

    # --------------------------------------------------------------------------------- plumbing
    @property
    def name(self) -> str:
        return self.table if self.schema == "public" else f"{self.schema}.{self.table}"

    def _q(self, ident: str) -> str:
        return self.engine.dialect.identifier_preparer.quote(ident)

    def _qualified(self) -> str:
        return f"{self._q(self.schema)}.{self._q(self.table)}"

    def _run(self, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
        """One short READ ONLY transaction: nothing stays open between pages, and a slow table cannot hang an audit."""
        with self.engine.connect() as conn:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = '{'8s' if self.fast else STATEMENT_TIMEOUT}'"))
            return list(conn.execute(text(sql), params or {}).mappings().all())

    def _call(self, fn: Any) -> Any:
        return call_with_retry(fn, stats=self.scan_stats, deadline=self.deadline, attempts=self.retry_attempts, sleep=self._sleep)

    def types(self) -> dict[str, str]:
        if self._types is None:
            rows = self._call(lambda: self._run(
                "SELECT column_name, udt_name FROM information_schema.columns WHERE table_schema = :s AND table_name = :t",
                {"s": self.schema, "t": self.table}))
            self._types = {r["column_name"]: r["udt_name"] for r in rows}
        return self._types

    def _column_of(self, canon: str) -> tuple[str, tuple[str, ...]] | None:
        """The column (and JSON path) behind one of our fields, if the table has that column."""
        column, path = parse_path(self.cmap[canon], canon)
        return (column, path) if column in self.types() else None

    def _need(self, canon: str, hint: str) -> tuple[str, tuple[str, ...]]:
        found = self._column_of(canon)
        if found is None:
            wanted = self.cmap[canon].split(".")[0]
            raise ConnectorError(f"Table {self.name} has no column '{wanted}' ({canon}). {hint}")
        return found

    def _expr(self, canon: str) -> tuple[str, str] | None:
        """(SQL expression, how its values compare: "number" or "text") for one of our fields, or None if the table lacks it."""
        found = self._column_of(canon)
        if found is None:
            return None
        column, path = found
        udt = self.types()[column]
        if path:
            if udt not in JSON_TYPES:
                return None
            return f"({self._q(column)} #>> '{{{','.join(path)}}}')", "text"
        if udt in NUMBER_TYPES:
            return self._q(column), "number"
        return (self._q(column), "text") if udt in ("text", "varchar", "bpchar", "name") else (f"CAST({self._q(column)} AS TEXT)", "text")

    def _progress(self) -> None:
        cb = self.on_progress
        if cb is None or time.monotonic() - self._last_progress < 2.0:
            return
        self._last_progress = time.monotonic()
        try:
            cb(self.scan_stats)
        except Exception:
            pass

    # --------------------------------------------------------------------------------- meta
    def collections(self) -> list[str]:
        return [self.name]

    def estimated_points(self) -> int | None:
        try:
            n = self._call(lambda: self._run("SELECT CAST(reltuples AS bigint) AS n FROM pg_class WHERE oid = to_regclass(:q)",
                                             {"q": f"{self._q(self.schema)}.{self._q(self.table)}"}))
        except Exception:
            return None
        approx = int(n[0]["n"]) if n and n[0]["n"] is not None and n[0]["n"] >= 0 else None
        if approx is not None:
            self.scan_stats.estimated_total = approx
        return approx

    def vector_sizes(self) -> dict[str, int | None]:
        try:
            column = self._need("vector", "Map the column that holds the embedding.")[0]
            rows = self._run("SELECT a.atttypmod AS m FROM pg_attribute a WHERE a.attrelid = to_regclass(:q) AND a.attname = :c AND NOT a.attisdropped",
                             {"q": f"{self._q(self.schema)}.{self._q(self.table)}", "c": column})
            dim = int(rows[0]["m"]) if rows and rows[0]["m"] is not None and rows[0]["m"] > 0 else None
        except Exception:
            dim = None
        return {self.name: dim}

    # --------------------------------------------------------------------------------- scan
    def _where(self, scope: Scope | None) -> list[tuple[str, dict[str, Any]]]:
        """Server-side filters for a scope, one per batch of document ids (a document id is in exactly one batch)."""
        if scope is None or scope.is_full:
            return [("", {})]
        parts: list[str] = []
        params: dict[str, Any] = {}
        if scope.tenant:
            tenant = self._expr("tenant_id")
            if tenant is not None:
                clause = self._equals(tenant, [scope.tenant], "t", params)
                parts.append(clause)
        if scope.keys is None:
            return [(" AND ".join(parts), params)] if parts else [("", {})]
        doc = self._expr("document_id")
        if doc is None:
            raise ConnectorError(f"Table {self.name} has no usable column for document_id. Map it in the column map.")
        docs = sorted({d for _, d in scope.keys})
        out: list[tuple[str, dict[str, Any]]] = []
        for i in range(0, len(docs), FILTER_BATCH):
            p = dict(params)
            out.append((" AND ".join([*parts, self._equals(doc, docs[i:i + FILTER_BATCH], "d", p)]), p))
        return out  # no documents -> nothing to read

    @staticmethod
    def _equals(expr: tuple[str, str], values: list[str], prefix: str, params: dict[str, Any]) -> str:
        """``expression = ANY(:ids)`` with the ids in the form the column stores them: a number column is given numbers (an id that is
        not a plain number cannot be in it); anything else is compared as text."""
        sql, kind = expr
        if kind == "number":
            usable: list[Any] = sorted({n for n in (number_form(v) for v in values) if n is not None})
            if not usable:
                return "1 = 0"
        else:
            usable = sorted(set(values))
        params[prefix] = usable
        return f"{sql} = ANY(:{prefix})"

    def _select_list(self, with_vectors: bool) -> tuple[str, str, str | None]:
        """(the SELECT list, the id column, the vector column when its contents are wanted)."""
        id_col = self._need("id", "Map the column that holds the row id (the primary key), for example {\"id\": \"uuid\"}.")[0]
        columns = {id_col}
        for canon, _path in self.pmap.items():
            found = self._column_of(canon)
            if found is not None:
                columns.add(found[0])
        vec_col = self._column_of("vector")[0] if (with_vectors and self._column_of("vector")) else None
        select = ", ".join(self._q(c) for c in sorted(columns))
        if vec_col:
            select += f", CAST({self._q(vec_col)} AS TEXT) AS \"__vector\""
        return select, id_col, vec_col

    def scan(self, scope: Scope | None = None, with_vectors: bool = False) -> Iterator[IndexedChunk]:
        self._need("document_id", "Map the column that holds the document id in the column map.")
        select, id_col, vec_col = self._select_list(with_vectors)
        page = max(1, self.s.pgvector_page_size)
        read = 0
        for where, params in self._where(scope):
            last: Any = None
            while True:
                check_deadline(self.deadline, "the vector index", f" ({read:,} rows so far)")
                clauses = [c for c in (where, f"{self._q(id_col)} > :lastid" if last is not None else "") if c]
                sql = (f"SELECT {select} FROM {self._qualified()}" + (" WHERE " + " AND ".join(clauses) if clauses else "")
                       + f" ORDER BY {self._q(id_col)} LIMIT {page}")
                bound = {**params, **({"lastid": last} if last is not None else {})}
                rows = self._call(lambda sql=sql, bound=bound: self._run(sql, bound))
                read += len(rows)
                self.scan_stats.pages += 1
                self._progress()
                for r in rows:
                    row = dict(r)
                    vector = parse_vector(row.pop("__vector", None)) if vec_col else None
                    chunk = payload_to_chunk(self.name, row[id_col], row, self.pmap, vector=vector, check_vector=bool(vec_col))
                    if scope is not None and not scope.is_full and chunk.document_id:
                        if not scope.matches((chunk.tenant_id or self.s.default_tenant, chunk.document_id)):
                            continue
                    yield chunk
                if len(rows) < page:
                    break
                last = rows[-1][id_col]

    # --------------------------------------------------------------------------------- a look at the ids (setup check)
    def id_sample(self, limit: int = 1000) -> dict[str, Any]:
        """The document and tenant ids of a sample of rows, exactly as stored. Reads ids only; never vectors."""
        self._need("document_id", "Map the column that holds the document id in the column map.")
        columns = sorted({self._column_of(c)[0] for c in ("document_id", "tenant_id", "source_hash", "source_version") if self._column_of(c)})
        approx = self.estimated_points()
        random_sample = False
        sample = ""
        if approx and approx > limit * 4:  # a block sample is cheap on a big table; a small table is read in full anyway
            sample = f" TABLESAMPLE SYSTEM ({min(100.0, max(0.001, 100.0 * limit * 3 / approx)):.4f})"
            random_sample = True
        check_deadline(self.deadline, "the vector index", " (sampling)")
        rows = self._call(lambda: self._run(f"SELECT {', '.join(self._q(c) for c in columns)} FROM {self._qualified()}{sample} LIMIT {int(limit)}"))
        if not rows and sample:  # the sample came back empty by chance
            random_sample = False
            rows = self._call(lambda: self._run(f"SELECT {', '.join(self._q(c) for c in columns)} FROM {self._qualified()} LIMIT {int(limit)}"))
        out = []
        for r in rows:
            row = dict(r)
            out.append({"collection": self.name, "point_id": "", "document_id": _dig(row, self.pmap["document_id"]),
                        "tenant_id": _dig(row, self.pmap["tenant_id"]),
                        "has_revision": any(_dig(row, self.pmap[f]) not in (None, "") for f in ("source_hash", "source_version"))})
        return {"rows": out, "random": random_sample or len(out) < limit, "approx_points": approx, "collections": [self.name]}

    # --------------------------------------------------------------------------------- probe
    def probe(self, collection: str, point_id: str, tenant_id: str | None, top_k: int) -> list[tuple[str, float, str | None]] | None:
        """Search with the stored vector of one row and return the ranked hits as ``(row id, score, document id)``. The score is higher
        for closer rows whichever distance the table uses (cosine similarity; the negated distance for L2 and inner product)."""
        id_col = self._need("id", "Map the column that holds the row id.")[0]
        vec_col = self._need("vector", "Map the column that holds the embedding.")[0]
        udt = self.types()[id_col]
        pid: Any = int(point_id) if udt in NUMBER_TYPES and point_id.lstrip("-").isdigit() else point_id
        eq = f"{self._q(id_col)} = CAST(:pid AS uuid)" if udt == "uuid" else f"{self._q(id_col)} = :pid"
        tenant = self._expr("tenant_id")
        doc = self._expr("document_id")
        select = f"CAST({self._q(vec_col)} AS TEXT) AS v" + (f", {tenant[0]} AS tenant" if tenant else "")
        rows = self._call(lambda: self._run(f"SELECT {select} FROM {self._qualified()} WHERE {eq} LIMIT 1", {"pid": pid}))
        if not rows or rows[0]["v"] is None:
            return None
        vec = parse_vector(rows[0]["v"])
        if not vec:
            return None
        # A real query is scoped to its tenant, so the probe is too, but only when the rows have a tenant at all (see the Qdrant probe).
        own = rows[0]["tenant"] if tenant else None
        params: dict[str, Any] = {"q": "[" + ",".join(repr(float(x)) for x in vec) + "]", "k": int(top_k)}
        where = ""
        if tenant is not None and tenant_id is not None and own is not None:
            where = f" WHERE {tenant[0]} = :own"
            params["own"] = own
        op = DISTANCES[self.distance]
        select = f"{self._q(id_col)} AS id, {self._q(vec_col)} {op} CAST(:q AS vector) AS d" + (f", {doc[0]} AS doc" if doc else "")
        hits = self._call(lambda: self._run(f"SELECT {select} FROM {self._qualified()}{where} ORDER BY d LIMIT :k", params))
        out: list[tuple[str, float, str | None]] = []
        for h in hits:
            d = float(h["d"])
            out.append((str(h["id"]), (1.0 - d) if self.distance == "cosine" else -d, None if doc is None or h["doc"] is None else str(h["doc"])))
        return out

    # --------------------------------------------------------------------------------- diagnostics
    def diagnose(self) -> list[dict[str, str]]:
        """Specific, actionable checks for the 'Test connection' button."""
        def chk(name: str, status: str, detail: str) -> dict[str, str]:
            return {"name": name, "status": status, "detail": detail}

        try:
            self._run("SELECT 1")
        except Exception as exc:
            return [chk("Database reachable", "fail", _explain_pg(exc))]
        out = [chk("Database reachable", "ok", "connected")]
        try:
            ext = self._run("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        except Exception:
            ext = []
        out.append(chk("pgvector extension", "ok" if ext else "warn",
                       f"version {ext[0]['extversion']}" if ext else
                       "the 'vector' extension is not installed in this database, so the retrieval tests cannot run (CREATE EXTENSION vector)."))
        try:
            types = self.types()
        except Exception as exc:
            return [*out, chk("Table", "fail", _explain_pg(exc))]
        if not types:
            return [*out, chk("Table", "fail", f"table {self.name} was not found, or this role cannot see it. Check the schema and table name.")]
        out.append(chk("Table", "ok", f"{self.name}: {len(types)} column(s)"))
        problems = []
        for canon, hint in (("document_id", "Map the column that holds the document id."), ("id", "Map the column that holds the row id (the primary key).")):
            if self._column_of(canon) is None:
                problems.append(chk(f"Column for {canon}", "fail", f"no column '{self.cmap[canon].split('.')[0]}'. {hint}"))
        if problems:
            return [*out, *problems]
        vec = self._column_of("vector")
        if vec is None:
            out.append(chk("Vector column", "warn", f"no column '{self.cmap['vector'].split('.')[0]}': the retrieval tests and empty-vector checks cannot run. Map the embedding column."))
        elif types[vec[0]] != "vector":
            out.append(chk("Vector column", "warn", f"'{vec[0]}' is a {types[vec[0]]} column, not a pgvector 'vector': the retrieval tests need pgvector."))
        else:
            dim = self.vector_sizes().get(self.name)
            out.append(chk("Vector column", "ok", f"'{vec[0]}' holds {dim}-dimensional vectors" if dim else f"'{vec[0]}' is a vector column (no fixed size)"))
        n = self.estimated_points()
        sample: list[Any] = []
        try:
            sample = self._run(f"SELECT * FROM {self._qualified()} LIMIT 20")
        except Exception as exc:
            out.append(chk("Rows", "fail", _explain_pg(exc)))
            return out
        out.append(chk("Rows", "ok" if sample else "warn", f"about {n:,} row(s)" if n and n > 0 else ("the table has rows" if sample else "the table is empty")))
        if sample:
            have = {c for c in self.pmap for r in sample if _dig(dict(r), self.pmap[c]) not in (None, "")}
            if "document_id" not in have:
                out.append(chk("Document ids", "fail", "the sampled rows have no value in the document id column. Check the column map."))
            else:
                needed = [f for f in ("source_hash",) if f not in have]
                extras = [f for f in ("tenant_id", "chunk_id", "chunk_index", "chunk_total") if f in have]
                out.append(chk("Fields used for checks", "warn" if needed else "ok",
                               f"the sampled rows lack {', '.join(needed)}: without a hash on each row a changed file cannot be told from an unchanged one."
                               if needed else f"found document_id and source_hash; also {', '.join(extras) or 'no other mapped fields'}"))
        try:
            writes = self._run("SELECT has_table_privilege(current_user, to_regclass(:q), 'INSERT') OR has_table_privilege(current_user, to_regclass(:q), 'UPDATE') "
                               "OR has_table_privilege(current_user, to_regclass(:q), 'DELETE') AS w", {"q": f"{self._q(self.schema)}.{self._q(self.table)}"})
            can = bool(writes and writes[0]["w"])
            out.append(chk("Role is read-only", "warn" if can else "ok",
                           "this database role CAN write to the table. RAGGuard only reads (every query is READ ONLY), but a SELECT-only role is safer."
                           if can else "this role has no write privileges on the table"))
        except Exception:
            pass
        return out

    # --------------------------------------------------------------------------------- health
    def health(self) -> ConnectionStatus:
        t0 = time.perf_counter()
        label = "Vector index (pgvector)"
        try:
            types = self.types()
            if not types:
                return ConnectionStatus(label, "pgvector", False, f"table {self.name} not found, or this role cannot see it")
            if self._column_of("document_id") is None:
                return ConnectionStatus(label, "pgvector", False, f"{self.name} has no column for document_id: map it in the column map")
            if self._column_of("id") is None:
                return ConnectionStatus(label, "pgvector", False, f"{self.name} has no id column: map the row id in the column map")
            n = self.estimated_points()
            ms = (time.perf_counter() - t0) * 1000
            detail = f"{self.name}: " + (f"~{n:,} rows" if n and n > 0 else "rows not counted yet")
            return ConnectionStatus(label, "pgvector", True, detail, ms, {"counts": {self.name: n or 0}})
        except Exception as exc:
            return ConnectionStatus(label, "pgvector", False, _explain_pg(exc))
