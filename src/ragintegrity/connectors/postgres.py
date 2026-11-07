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
from sqlalchemy.engine import Engine

from ..config import Settings, check_identifier, normalize_db_url
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


def make_engine(url: str) -> Engine:
    url = normalize_db_url(url)
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "pool_size": 3, "max_overflow": 2}
    if url.startswith("sqlite"):
        kwargs = {}
    elif "+psycopg" in url:
        kwargs["connect_args"] = {"prepare_threshold": None}  # safe behind Supabase's transaction pooler
    return create_engine(url, **kwargs)


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


class PostgresManifest:
    def __init__(self, settings: Settings, engine: Engine | None = None) -> None:
        if engine is None:
            if not settings.manifest_database_url:
                raise ConnectorError("RAGI_MANIFEST_DATABASE_URL is not set")
            engine = make_engine(settings.manifest_database_url)
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
        cols = {c["name"] for c in insp.get_columns(table, schema=self.schema)}
        return {canon: actual for canon, actual in cmap.items() if actual in cols}

    def _stream(self, sql: str, params: dict[str, Any]) -> Iterator[Any]:
        with self.engine.connect() as conn:
            if self.engine.dialect.name == "postgresql":
                conn.execute(text("SET TRANSACTION READ ONLY"))
            result = conn.execution_options(stream_results=True).execute(text(sql), params)
            yield from result.mappings()

    def _where(self, scope: Scope | None, present: dict[str, str]) -> tuple[str, dict[str, Any], bool]:
        """Return (where clause, params, needs_python_filter)."""
        if scope is None or scope.is_full:
            return "", {}, False
        q = self.engine.dialect.identifier_preparer.quote
        parts: list[str] = []
        params: dict[str, Any] = {}
        if scope.tenant and "tenant_id" in present:
            parts.append(f"{q(present['tenant_id'])} = :tenant")
            params["tenant"] = scope.tenant
        python_filter = scope.tenant is not None and "tenant_id" not in present
        if scope.keys is not None:
            if len(scope.keys) <= KEYS_IN_LIMIT and "document_id" in present:
                ids = sorted({d for _, d in scope.keys})
                names = []
                for i, d in enumerate(ids):
                    params[f"d{i}"] = d
                    names.append(f":d{i}")
                parts.append(f"{q(present['document_id'])} IN ({', '.join(names)})")
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
        where, params, py_filter = self._where(scope, present)
        sql = f"SELECT {select} FROM {self._qualified(self.table)}{where}"
        for r in self._stream(sql, params):
            tenant = _s(r.get("tenant_id")) or self.s.default_tenant
            key = (tenant, str(r["document_id"]))
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
        where, params, py_filter = self._where(scope, present)
        sql = f"SELECT {select} FROM {self._qualified(self.chunk_table)}{where}"
        for r in self._stream(sql, params):
            tenant = _s(r.get("tenant_id")) or self.s.default_tenant
            if py_filter and scope is not None and not scope.matches((tenant, str(r["document_id"]))):
                continue
            yield ChunkRow(tenant, str(r["document_id"]), str(r["chunk_id"]), _i(r.get("chunk_index")),
                           _s(r.get("chunk_hash")))

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
