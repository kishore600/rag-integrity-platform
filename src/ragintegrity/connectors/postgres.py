"""Read-only view of the customer's processing manifest in PostgreSQL / Supabase.

The manifest table/columns are configurable. Every statement runs in a ``READ ONLY`` transaction, and
identifiers (schema/table/column names) are validated before being quoted into SQL.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy import types as sqltypes
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ..config import Settings, check_identifier, normalize_db_url
from ..ids import normalize_id, number_form
from ..models import ChunkRow, ConnectionStatus, Fingerprint, ManifestRow, Scope
from .base import ConnectorError

DOC_COLUMNS = (
    "tenant_id", "document_id", "source_uri", "source_version", "source_hash", "parsed_hash", "parser_version",
    "chunking_version", "chunk_size", "chunk_overlap", "embedding_model", "embedding_model_version",
    "embedding_dim", "preprocessing", "expected_chunk_count", "indexed_chunk_count", "indexed_version",
    "processing_status", "last_verified_at", "updated_at", "acl_hash",
)
CHUNK_COLUMNS = ("tenant_id", "document_id", "chunk_id", "chunk_index", "chunk_hash")
KEYS_IN_LIMIT = 400


def make_engine(url: str, null_pool: bool = False) -> Engine:
    """``null_pool`` opens a fresh connection per use and never keeps one: right for short-lived connections to a
    *customer's* database from a serverless function, where pooled connections would just leak."""
    url = normalize_db_url(url)
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "pool_size": 2, "max_overflow": 3, "pool_recycle": 300}
    if url.startswith("sqlite"):
        kwargs = {}
    else:
        if null_pool:
            kwargs = {"poolclass": NullPool}
        if "+psycopg" in url:
            kwargs["connect_args"] = {"prepare_threshold": None, "connect_timeout": 10}  # safe behind Supabase's pooler
    return create_engine(url, **kwargs)


def _explain_pg(exc: Exception) -> str:
    """A connection error message that helps, without echoing the connection string or password."""
    msg = str(getattr(exc, "orig", exc)).strip().splitlines()[0] if str(exc) else type(exc).__name__
    low = msg.lower()
    if "password authentication failed" in low or "authentication failed" in low:
        return "Authentication failed: check the user name and password in the connection string."
    if "timeout" in low or "timed out" in low:
        return "Connection timed out: the host is unreachable from the internet or a firewall blocks this server."
    if "could not translate host" in low or "name or service not known" in low or "nodename nor servname" in low:
        return "The host name could not be resolved."
    if "ssl" in low:
        return "SSL negotiation failed: try adding ?sslmode=require to the connection string."
    if "does not exist" in low:
        return msg[:200]
    if "permission denied" in low:
        return "Permission denied: the role cannot read this table."
    return f"{type(exc).__name__}: {msg[:160]}"


def _iso(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        from datetime import timezone

        v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(v)


def _s(v: Any) -> str | None:
    return None if v is None else str(v)


def _i(v: Any) -> int | None:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def _id(v: Any) -> str | None:
    """A document, tenant or chunk id as text: 170 (a bigint column), 170.00 (a numeric column) and "170" are one id."""
    return None if v is None or v == "" else normalize_id(v)


class PostgresManifest:
    def __init__(self, settings: Settings, engine: Engine | None = None) -> None:
        if engine is None:
            if not settings.manifest_database_url:
                raise ConnectorError("RAGI_MANIFEST_DATABASE_URL is not set")
            engine = make_engine(settings.manifest_database_url, null_pool=True)
        self.engine = engine
        self.s = settings
        self.schema = check_identifier(settings.manifest_schema, "RAGI_MANIFEST_SCHEMA") if engine.dialect.name != "sqlite" else None
        self.table = check_identifier(settings.manifest_table, "RAGI_MANIFEST_TABLE")
        self.chunk_table = (
            check_identifier(settings.manifest_chunk_table, "RAGI_MANIFEST_CHUNK_TABLE")
            if settings.manifest_chunk_table else None
        )
        self.has_chunk_manifest = self.chunk_table is not None
        self.doc_map = self._column_map(settings.manifest_columns, DOC_COLUMNS)
        self.chunk_map = self._column_map(settings.manifest_chunk_columns, CHUNK_COLUMNS)
        self.empty_ids = 0  # manifest rows skipped because their document id column was empty (counted per read)
        self._types: dict[str, dict[str, Any]] = {}  # table -> column name -> SQL type (read together with the column names)

    @staticmethod
    def _column_map(overrides: dict[str, str], canonical: tuple[str, ...]) -> dict[str, str]:
        m = {c: c for c in canonical}
        for k, v in overrides.items():
            if k not in m:
                raise ConnectorError(f"Unknown manifest column {k!r}; valid: {', '.join(canonical)}")
            m[k] = check_identifier(v, f"column for {k}")
        return m

    # --------------------------------------------------------------------------------- helpers
    def _qualified(self, table: str) -> str:
        q = self.engine.dialect.identifier_preparer.quote
        return f"{q(self.schema)}.{q(table)}" if self.schema else q(table)

    def _existing(self, table: str, cmap: dict[str, str]) -> dict[str, str]:
        insp = inspect(self.engine)
        columns = {c["name"]: c["type"] for c in insp.get_columns(table, schema=self.schema)}
        self._types[table] = columns
        return {canon: actual for canon, actual in cmap.items() if actual in columns}

    def _in_clause(self, table: str, column: str, values: list[str], prefix: str, params: dict[str, Any]) -> str:
        """``column IN (...)`` for ids written as text, in the form the column stores them.

        Comparing text with a number column fails for any value that is not a number (Postgres cannot cast 'abc' to
        bigint), and a text column never matches a number. So a number column is given numbers (an id that is not
        a plain number cannot be in it), and a column of any other type is compared as text."""
        q = self.engine.dialect.identifier_preparer.quote
        ctype = self._types.get(table, {}).get(column)
        col = q(column)
        if isinstance(ctype, (sqltypes.Integer, sqltypes.Numeric, sqltypes.Float)):
            usable: list[Any] = sorted({n for n in (number_form(v) for v in values) if n is not None})
            if not usable:
                return "1 = 0"
        else:
            usable = sorted(set(values))
            if ctype is not None and not isinstance(ctype, sqltypes.String):  # uuid, enums, ...: their text form
                col = f"CAST({col} AS TEXT)"
        names = []
        for i, v in enumerate(usable):
            params[f"{prefix}{i}"] = v
            names.append(f":{prefix}{i}")
        return f"{col} IN ({', '.join(names)})"

    def _stream(self, sql: str, params: dict[str, Any]) -> Iterator[Any]:
        with self.engine.connect() as conn:
            if self.engine.dialect.name == "postgresql":
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text("SET LOCAL statement_timeout = '45s'"))  # a customer's slow table must not hang an audit
            result = conn.execution_options(stream_results=True).execute(text(sql), params)
            yield from result.mappings()

    def _where(self, scope: Scope | None, present: dict[str, str], table: str) -> tuple[str, dict[str, Any], bool]:
        """Return (where clause, params, needs_python_filter)."""
        if scope is None or scope.is_full:
            return "", {}, False
        parts: list[str] = []
        params: dict[str, Any] = {}
        if scope.tenant and "tenant_id" in present:
            parts.append(self._in_clause(table, present["tenant_id"], [scope.tenant], "t", params))
        python_filter = scope.tenant is not None and "tenant_id" not in present
        if scope.keys is not None:
            if len(scope.keys) <= KEYS_IN_LIMIT and "document_id" in present:
                parts.append(self._in_clause(table, present["document_id"], sorted({d for _, d in scope.keys}), "d", params))
            # the SQL filter only narrows by document id; exact (tenant, document) pairs are re-checked in Python
            python_filter = True
        return (" WHERE " + " AND ".join(parts)) if parts else "", params, python_filter

    # --------------------------------------------------------------------------------- reads
    def documents(self, scope: Scope | None = None) -> Iterator[ManifestRow]:
        present = self._existing(self.table, self.doc_map)
        if "document_id" not in present:
            raise ConnectorError(f"Manifest table {self.table} has no column '{self.doc_map['document_id']}' (document_id)")
        q = self.engine.dialect.identifier_preparer.quote
        select = ", ".join(f"{q(actual)} AS {q(canon)}" for canon, actual in present.items())
        where, params, py_filter = self._where(scope, present, self.table)
        sql = f"SELECT {select} FROM {self._qualified(self.table)}{where}"
        self.empty_ids = 0
        for r in self._stream(sql, params):
            tenant = _id(r.get("tenant_id")) or self.s.default_tenant
            doc = _id(r["document_id"])
            if doc is None:  # a row without an id cannot be matched to anything: count it instead of calling it "None"
                self.empty_ids += 1
                continue
            key = (tenant, doc)
            if py_filter and scope is not None and not scope.matches(key):
                continue
            yield ManifestRow(
                tenant_id=tenant, document_id=key[1], source_uri=_s(r.get("source_uri")),
                source_version=_s(r.get("source_version")), source_hash=_s(r.get("source_hash")),
                parsed_hash=_s(r.get("parsed_hash")),
                fingerprint=Fingerprint(
                    parser_version=_s(r.get("parser_version")), chunking_version=_s(r.get("chunking_version")),
                    chunk_size=_i(r.get("chunk_size")), chunk_overlap=_i(r.get("chunk_overlap")),
                    embedding_model=_s(r.get("embedding_model")),
                    embedding_model_version=_s(r.get("embedding_model_version")),
                    embedding_dim=_i(r.get("embedding_dim")), preprocessing=_s(r.get("preprocessing")),
                ),
                expected_chunk_count=_i(r.get("expected_chunk_count")),
                indexed_chunk_count=_i(r.get("indexed_chunk_count")),
                indexed_version=_s(r.get("indexed_version")), processing_status=_s(r.get("processing_status")),
                last_verified_at=_iso(r.get("last_verified_at")), updated_at=_iso(r.get("updated_at")),
                acl_hash=_s(r.get("acl_hash")),
            )

    def chunks(self, scope: Scope | None = None) -> Iterator[ChunkRow]:
        if not self.chunk_table:
            return
        present = self._existing(self.chunk_table, self.chunk_map)
        if "document_id" not in present or "chunk_id" not in present:
            raise ConnectorError("Chunk manifest needs at least document_id and chunk_id columns")
        q = self.engine.dialect.identifier_preparer.quote
        select = ", ".join(f"{q(actual)} AS {q(canon)}" for canon, actual in present.items())
        where, params, py_filter = self._where(scope, present, self.chunk_table)
        sql = f"SELECT {select} FROM {self._qualified(self.chunk_table)}{where}"
        for r in self._stream(sql, params):
            tenant = _id(r.get("tenant_id")) or self.s.default_tenant
            doc, chunk = _id(r["document_id"]), _id(r["chunk_id"])
            if doc is None or chunk is None:
                continue
            if py_filter and scope is not None and not scope.matches((tenant, doc)):
                continue
            yield ChunkRow(tenant, doc, chunk, _i(r.get("chunk_index")), _s(r.get("chunk_hash")))

    def diagnose(self) -> list[dict[str, str]]:
        """Specific, actionable checks for the 'Test connection' button."""
        def chk(name: str, status: str, detail: str) -> dict[str, str]:
            return {"name": name, "status": status, "detail": detail}

        out: list[dict[str, str]] = []
        try:
            with self.engine.connect() as c:
                c.execute(text("SELECT 1"))
        except Exception as exc:
            return [chk("Database reachable", "fail", _explain_pg(exc))]
        out.append(chk("Database reachable", "ok", f"connected ({self.engine.dialect.name})"))
        try:
            present = self._existing(self.table, self.doc_map)
        except Exception as exc:
            out.append(chk("Manifest table", "fail", f"could not inspect {self.table}: {type(exc).__name__}. Check schema/table names and that the role can read them."))
            return out
        if not present:
            out.append(chk("Manifest table", "fail", f"table {self.schema + '.' if self.schema else ''}{self.table} was not found or has no mapped columns."))
            return out
        if "document_id" not in present:
            out.append(chk("Manifest table", "fail", f"no column for document_id (looked for '{self.doc_map['document_id']}'). Map it with the column map."))
            return out
        important = [c for c in ("source_hash", "processing_status", "expected_chunk_count", "indexed_chunk_count") if c not in present]
        out.append(chk("Manifest table", "ok", f"{len(present)} of {len(self.doc_map)} columns mapped"))
        if important:
            out.append(chk("Columns used for checks", "warn", f"missing {', '.join(important)}: the related checks (stale / partial / false-success detection) are reduced."))
        rows: Any = None
        try:
            with self.engine.connect() as c:
                if self.engine.dialect.name == "postgresql":
                    c.execute(text("SET TRANSACTION READ ONLY"))
                rows = c.execute(text(f"SELECT count(*) FROM (SELECT 1 FROM {self._qualified(self.table)} LIMIT 100001) s")).scalar_one()
            out.append(chk("Rows", "ok" if rows else "warn",
                           (f"{rows if rows <= 100000 else '100000+'} manifest row(s)" if rows else "the manifest table is empty")))
        except Exception as exc:
            out.append(chk("Rows", "fail", _explain_pg(exc)))
        if self.engine.dialect.name == "postgresql":
            try:
                with self.engine.connect() as c:
                    qn = f"{self.schema}.{self.table}"
                    writes = c.execute(text("SELECT has_table_privilege(current_user, :t, 'INSERT') OR has_table_privilege(current_user, :t, 'UPDATE') "
                                            "OR has_table_privilege(current_user, :t, 'DELETE')"), {"t": qn}).scalar_one()
                out.append(chk("Role is read-only", "warn" if writes else "ok",
                               "this database role CAN write to the manifest table. RAG Integrity only reads (every query is READ ONLY), "
                               "but a SELECT-only role is safer." if writes else "this role has no write privileges on the manifest table"))
            except Exception:
                pass
        if self.chunk_table:
            try:
                cp = self._existing(self.chunk_table, self.chunk_map)
                ok = "document_id" in cp and "chunk_id" in cp
                out.append(chk("Chunk manifest", "ok" if ok else "fail",
                               f"{self.chunk_table}: {len(cp)} columns mapped" if ok else f"{self.chunk_table} needs document_id and chunk_id columns"))
            except Exception as exc:
                out.append(chk("Chunk manifest", "fail", _explain_pg(exc)))
        else:
            out.append(chk("Chunk manifest", "warn", "not configured: partial indexes are detected from chunk counts and index gaps instead of exact chunk ids."))
        return out

    def health(self) -> ConnectionStatus:
        t0 = time.perf_counter()
        try:
            present = self._existing(self.table, self.doc_map)
            if not present:
                return ConnectionStatus("Manifest (Postgres)", "postgres", False,
                                        f"table {self.table} not found or has no mapped columns")
            missing = [c for c in self.doc_map if c not in present]
            ms = (time.perf_counter() - t0) * 1000
            detail = f"{self.table}: {len(present)}/{len(self.doc_map)} columns mapped"
            ok = "document_id" in present
            if not ok:
                detail = f"{self.table} has no document_id column"
            return ConnectionStatus("Manifest (Postgres)", "postgres", ok, detail, ms,
                                    {"mapped": sorted(present), "missing": missing,
                                     "chunk_table": self.chunk_table})
        except Exception as exc:
            return ConnectionStatus("Manifest (Postgres)", "postgres", False, f"{type(exc).__name__}: {str(exc)[:200]}")
