"""Runtime configuration, read from environment variables (prefix ``RAGI_``) or a local ``.env``.

Secrets (database passwords, API keys) only ever live in the environment. They are never
written to the ledger database.
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import Fingerprint

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def check_identifier(value: str, what: str) -> str:
    """SQL identifiers come from config, so validate them before they are ever quoted into a query."""
    if not IDENT_RE.match(value):
        raise ValueError(f"Invalid {what} {value!r}: only letters, digits and underscores are allowed")
    return value


def normalize_db_url(url: str) -> str:
    """Accept plain postgres:// URLs (as Supabase shows them) and select the psycopg3 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAGI_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- general -------------------------------------------------------------------------
    mode: str = "demo"  # demo = built-in synthetic world | live = S3 + Postgres + Qdrant
    database_url: str = "sqlite:///./data/ragi.db"  # control plane / issue ledger (Supabase Postgres in prod)
    api_key: str | None = None  # if set, /api/* requires it (X-API-Key or Bearer)
    audit_interval_minutes: int = 0  # 0 disables the built-in scheduler
    sync_audits: bool = False  # run API-started audits inside the request (automatic on Vercel/serverless)
    grace_minutes: int = 10  # don't flag documents that are probably still being ingested
    required_payload_fields: str = ""  # comma separated; default document_id,source_hash(+tenant_id if multi-tenant)

    # --- source: S3 -------------------------------------------------------------------------
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_region: str | None = None
    s3_endpoint_url: str | None = None  # MinIO / localstack
    s3_hash_mode: str = "metadata"  # metadata | compute | etag
    s3_sha256_metadata_key: str = "sha256"
    s3_key_pattern: str = r"^(?P<tenant_id>[^/]+)/(?P<document_id>.+)$"
    s3_default_tenant: str = "default"
    s3_workers: int = 16

    # --- processing manifest: PostgreSQL / Supabase ------------------------------------------
    manifest_database_url: str | None = None
    manifest_schema: str = "public"
    manifest_table: str = "rag_document_manifest"
    manifest_chunk_table: str | None = None  # optional chunk-level manifest (stable chunk ids / hashes)
    manifest_column_map: str = ""  # JSON: {"canonical_name": "your_column"}
    manifest_chunk_column_map: str = ""

    # --- vector index: Qdrant ---------------------------------------------------------------------
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_collections: str = ""  # comma separated
    qdrant_payload_map: str = ""  # JSON: {"document_id": "doc_id", ...}
    qdrant_vector_name: str | None = None
    qdrant_check_vectors: bool = False  # also pull vectors to find empty / all-zero embeddings (slower)
    qdrant_page_size: int = 1000
    default_tenant: str = "default"  # tenant to assume when a payload has no tenant field

    # --- target pipeline fingerprint (what *should* be in the index) -------------------------------
    target_parser_version: str | None = None
    target_chunking_version: str | None = None
    target_chunk_size: int | None = None
    target_chunk_overlap: int | None = None
    target_embedding_model: str | None = None
    target_embedding_model_version: str | None = None
    target_embedding_dim: int | None = None
    target_preprocessing: str | None = None

    # --- retrieval probes -------------------------------------------------------------------------
    probe_retrieval: bool = True
    probe_max: int = 25
    probe_top_k: int = 10

    # --- repair, alerts, cost -----------------------------------------------------------------------
    repair_webhook_url: str | None = None  # the customer's own worker; use demo://worker in demo mode
    repair_webhook_secret: str | None = None  # HMAC key shared with the worker
    public_base_url: str | None = None  # used to build callback URLs sent to the worker
    cleanup_policy: str = "manual"  # manual = an operator must approve vector removal
    alert_webhook_url: str | None = None  # Slack-compatible incoming webhook
    alert_min_severity: str = "high"
    embedding_price_per_mtok: float = 0.13  # USD per 1M tokens, for workload estimates
    chunk_size_tokens: int = 512

    # ------------------------------------------------------------------------------------------
    def target_fingerprint(self) -> Fingerprint | None:
        fp = Fingerprint(
            parser_version=self.target_parser_version,
            chunking_version=self.target_chunking_version,
            chunk_size=self.target_chunk_size,
            chunk_overlap=self.target_chunk_overlap,
            embedding_model=self.target_embedding_model,
            embedding_model_version=self.target_embedding_model_version,
            embedding_dim=self.target_embedding_dim,
            preprocessing=self.target_preprocessing,
        )
        return None if fp.is_empty() else fp

    @property
    def collections(self) -> list[str]:
        return [c.strip() for c in self.qdrant_collections.split(",") if c.strip()]

    @property
    def required_fields(self) -> list[str]:
        return [c.strip() for c in self.required_payload_fields.split(",") if c.strip()]

    @staticmethod
    def _json_map(raw: str, what: str) -> dict[str, Any]:
        if not raw.strip():
            return {}
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{what} must be valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{what} must be a JSON object")
        return value

    @property
    def payload_map(self) -> dict[str, str]:
        return self._json_map(self.qdrant_payload_map, "RAGI_QDRANT_PAYLOAD_MAP")

    @property
    def manifest_columns(self) -> dict[str, str]:
        return self._json_map(self.manifest_column_map, "RAGI_MANIFEST_COLUMN_MAP")

    @property
    def manifest_chunk_columns(self) -> dict[str, str]:
        return self._json_map(self.manifest_chunk_column_map, "RAGI_MANIFEST_CHUNK_COLUMN_MAP")

    @property
    def is_demo(self) -> bool:
        return self.mode.lower() == "demo"

    @property
    def run_audits_inline(self) -> bool:
        """Serverless platforms freeze or kill background threads once the response is sent, so audits must
        finish inside the request there."""
        return self.sync_audits or bool(os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
