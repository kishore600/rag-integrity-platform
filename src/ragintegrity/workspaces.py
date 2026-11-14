"""Per-workspace configuration: what a user can connect, validation, encryption, and the per-workspace service.

Every user has one workspace. A workspace's connections (S3, the processing manifest, Qdrant, pipeline target,
repair webhook, alerts, policy) are described declaratively in ``SPECS``; the same spec drives validation, the
settings forms in the dashboard, and the mapping onto the engine's ``Settings``.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any

from .accounts import AccountError, Accounts
from .config import Settings, check_identifier
from .connectors.base import ConnectorError, SetupIncomplete
from .connectors.factory import Connectors, build_connectors
from .ledger import Ledger, iso, utcnow
from .security import UnsafeTarget, assert_public_url, validate_postgres_url
from .service import IntegrityService


@dataclass(frozen=True)
class Field:
    name: str
    setting: str  # the engine Settings attribute this maps onto
    label: str
    type: str = "str"  # str | int | float | bool | enum | url | pgurl | json | ident | regex | csv
    secret: bool = False
    required: bool = False
    help: str = ""
    placeholder: str = ""
    choices: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    max_len: int = 512


@dataclass(frozen=True)
class Spec:
    title: str
    description: str
    fields: tuple[Field, ...]


SPECS: dict[str, Spec] = {
    "s3": Spec(
        "Source documents (S3)",
        "Where your documents live. Read-only: list + head (and get only in 'compute' hash mode). Works with AWS S3 and S3-compatible stores.",
        (
            Field("bucket", "s3_bucket", "Bucket", required=True, placeholder="my-company-docs", max_len=255),
            Field("prefix", "s3_prefix", "Key prefix", help="Optional. Only keys under this prefix are audited.", placeholder="knowledge-base/"),
            Field("region", "s3_region", "Region", placeholder="us-east-1", max_len=64),
            Field("endpoint_url", "s3_endpoint_url", "Custom endpoint", type="url",
                  help="Leave empty for AWS S3. Set it for S3-compatible stores, e.g. https://<ref>.supabase.co/storage/v1/s3",
                  placeholder="https://s3.example.com"),
            Field("access_key_id", "s3_access_key_id", "Access key ID", secret=True, required=True, max_len=256),
            Field("secret_access_key", "s3_secret_access_key", "Secret access key", secret=True, required=True, max_len=256),
            Field("hash_mode", "s3_hash_mode", "Content hash", type="enum", choices=("metadata", "compute", "etag"),
                  help="metadata: read a sha256 stored with each object (fast). compute: download and hash (accurate, costs egress). "
                       "etag: quick start; multipart ETags are not content hashes."),
            Field("sha256_metadata_key", "s3_sha256_metadata_key", "SHA-256 metadata key", help="User-metadata key holding the sha256.",
                  placeholder="sha256", max_len=64),
            Field("key_pattern", "s3_key_pattern", "Key pattern (regex)", type="regex",
                  help="Must capture (?P<document_id>...) and optionally (?P<tenant_id>...). Default: <tenant>/<document path>.",
                  placeholder=r"^(?P<tenant_id>[^/]+)/(?P<document_id>.+)$", max_len=300),
            Field("default_tenant", "s3_default_tenant", "Default tenant", help="Used when keys carry no tenant.", placeholder="default", max_len=64),
            Field("lookup_from_manifest", "s3_lookup_from_manifest", "Look up files from the manifest (skip listing the bucket)",
                  type="bool",
                  help="Reads exactly the files the manifest's source URI column names (one HEAD request each, only files that match "
                       "the key pattern) instead of listing the whole bucket. Much faster for large buckets. Files that are in S3 "
                       "but not in the manifest are not discovered."),
        ),
    ),
    "manifest": Spec(
        "Processing manifest (PostgreSQL / Supabase)",
        "Optional. The table your pipeline writes after processing each document. Without it RAGGuard compares your files with the vector index "
        "directly; with it, it can also check what the pipeline claimed against what is indexed. Read-only: every query runs in a READ ONLY "
        "transaction. Use a role that can only SELECT.",
        (
            Field("database_url", "manifest_database_url", "Connection string", type="pgurl", secret=True, required=True,
                  help="postgresql://user:password@host:5432/dbname?sslmode=require", placeholder="postgresql://reader:***@db.example.com:5432/postgres?sslmode=require"),
            Field("schema", "manifest_schema", "Schema", type="ident", placeholder="public", max_len=63),
            Field("table", "manifest_table", "Document table", type="ident", placeholder="rag_document_manifest", max_len=63),
            Field("chunk_table", "manifest_chunk_table", "Chunk table (optional)", type="ident",
                  help="Lets the audit name exactly which chunks are missing.", placeholder="rag_chunk_manifest", max_len=63),
            Field("column_map", "manifest_column_map", "Column map (JSON)", type="json",
                  help='Map our column names to yours, e.g. {"document_id": "doc_ref", "processing_status": "state"}', max_len=4000),
            Field("chunk_column_map", "manifest_chunk_column_map", "Chunk column map (JSON)", type="json", max_len=4000),
        ),
    ),
    "qdrant": Spec(
        "Vector index (Qdrant)",
        "Your vector store. Read-only: scroll, retrieve and query. Qdrant Cloud: https://<cluster>.cloud.qdrant.io:6333",
        (
            Field("url", "qdrant_url", "URL", type="url", required=True, placeholder="https://xyz.cloud.qdrant.io:6333",
                  help="A URL without a port uses 6333. If Qdrant sits behind a TLS reverse proxy, add :443 explicitly."),
            Field("api_key", "qdrant_api_key", "API key", secret=True, help="A read-capable key. Leave empty for an open instance.", max_len=512),
            Field("collections", "qdrant_collections", "Collections", type="csv", placeholder="kb_main",
                  help="Comma separated. Empty means every collection."),
            Field("payload_map", "qdrant_payload_map", "Payload field map (JSON)", type="json",
                  help='If your payload uses other names, e.g. {"document_id": "doc_id", "tenant_id": "meta.tenant"}', max_len=4000),
            Field("vector_name", "qdrant_vector_name", "Named vector", help="Only if your collection uses named vectors.", max_len=64),
            Field("check_vectors", "qdrant_check_vectors", "Detect empty embeddings", type="bool",
                  help="Also fetches vectors to find empty or all-zero embeddings (slower)."),
        ),
    ),
    "index": Spec(
        "Where your vectors are stored",
        "Qdrant, or pgvector (a PostgreSQL table with a vector column: Supabase, Neon, AWS RDS and plain Postgres).",
        (
            Field("type", "index_type", "Vector store", type="enum", choices=("qdrant", "pgvector"),
                  help="qdrant: a Qdrant server or Qdrant Cloud. pgvector: a PostgreSQL table with a pgvector column."),
        ),
    ),
    "pgvector": Spec(
        "Vector index (pgvector / PostgreSQL)",
        "A PostgreSQL table with a pgvector column, one row per chunk. Read-only: every query runs in a READ ONLY transaction. "
        "Use a role that can only SELECT.",
        (
            Field("database_url", "pgvector_database_url", "Connection string", type="pgurl", secret=True, required=True,
                  help="postgresql://user:password@host:5432/dbname?sslmode=require", placeholder="postgresql://reader:***@db.example.com:5432/postgres?sslmode=require"),
            Field("schema", "pgvector_schema", "Schema", type="ident", placeholder="public", max_len=63),
            Field("table", "pgvector_table", "Table", type="ident", required=True, placeholder="documents_embeddings", max_len=63),
            Field("column_map", "pgvector_column_map", "Column map (JSON)", type="json",
                  help='Point our names at your columns. A key inside a JSON column works too: {"document_id": "doc_id", "source_hash": "content_hash", '
                       '"vector": "embedding", "tenant_id": "metadata.tenant"}. "id" is the row id (the primary key).', max_len=4000),
            Field("distance", "pgvector_distance", "Distance", type="enum", choices=("cosine", "l2", "inner_product"),
                  help="The operator your table's index uses (cosine is the usual one). It decides how the retrieval test searches."),
            Field("check_vectors", "pgvector_check_vectors", "Detect empty embeddings", type="bool",
                  help="Also reads the vectors to find empty or all-zero embeddings (slower)."),
        ),
    ),
    "pipeline": Spec(
        "Target pipeline",
        "How documents SHOULD currently be processed. Vectors built with a different configuration are reported as drift. All optional.",
        (
            Field("parser_version", "target_parser_version", "Parser version", max_len=64),
            Field("chunking_version", "target_chunking_version", "Chunking version", max_len=64),
            Field("chunk_size", "target_chunk_size", "Chunk size", type="int", min=1, max=1_000_000),
            Field("chunk_overlap", "target_chunk_overlap", "Chunk overlap", type="int", min=0, max=1_000_000),
            Field("embedding_model", "target_embedding_model", "Embedding model", max_len=128),
            Field("embedding_model_version", "target_embedding_model_version", "Embedding model version", max_len=64),
            Field("embedding_dim", "target_embedding_dim", "Embedding dimensions", type="int", min=1, max=65_536,
                  help="Also checked against every collection's vector size."),
            Field("preprocessing", "target_preprocessing", "Preprocessing", max_len=128),
        ),
    ),
    "repair": Spec(
        "Repair worker",
        "Your own ingestion worker. We never write to your systems: approved repairs are sent here as a signed webhook.",
        (
            Field("webhook_url", "repair_webhook_url", "Webhook URL", type="url", placeholder="https://worker.example.com/ragi-webhook"),
            Field("webhook_secret", "repair_webhook_secret", "Signing secret", secret=True, help="Shared HMAC key; required before anything is sent.", max_len=256),
            Field("cleanup_policy", "cleanup_policy", "Vector removal", type="enum", choices=("manual", "auto"),
                  help="manual: an operator approves removal. auto: removal is requested right after verification."),
        ),
    ),
    "alerts": Spec(
        "Alerts",
        "After every audit: a notification in the app and an email, each with the next step. Plus an optional Slack-compatible webhook "
        "for new, reopened or escalated issues.",
        (
            Field("email_when", "alert_email_when", "Email me", type="enum", choices=("always", "attention", "never"),
                  help="always: after every audit. attention: only when an audit fails or stops part-way, or finds a new issue at or above the "
                       "minimum severity. never: no email. The notification in the app is always created."),
            Field("webhook_url", "alert_webhook_url", "Webhook URL", type="url", secret=True, placeholder="https://hooks.slack.com/services/..."),
            Field("min_severity", "alert_min_severity", "Minimum severity", type="enum", choices=("critical", "high", "medium", "low")),
        ),
    ),
    "policy": Spec(
        "Audit policy",
        "Tuning knobs for audits and estimates.",
        (
            Field("grace_minutes", "grace_minutes", "Grace period (minutes)", type="int", min=0, max=1440,
                  help="Documents modified or being processed within this window are 'pending', not broken."),
            Field("default_tenant", "default_tenant", "Default tenant", help="Assumed when a payload or row has no tenant.", max_len=64),
            Field("required_payload_fields", "required_payload_fields", "Required payload fields", type="csv",
                  help="Default: document_id, source_hash (plus tenant_id once there are several tenants)."),
            Field("source_documents_only", "source_documents_only", "Only audit documents found in the source (S3)", type="bool",
                  help="The S3 key pattern decides which files count. Manifest rows and vectors for any other document are ignored, "
                       "and only the matching Qdrant points are read (fast on large shared collections). "
                       "Left-over vectors and manifest rows for deleted files are then not reported."),
            Field("embedding_price_per_mtok", "embedding_price_per_mtok", "Embedding price (USD per 1M tokens)", type="float", min=0, max=10_000),
            Field("chunk_size_tokens", "chunk_size_tokens", "Tokens per chunk (for estimates)", type="int", min=1, max=100_000),
        ),
    ),
}
REQUIRED_KINDS = ("s3", "qdrant")  # the default: S3 and the index. The manifest is optional; the index is pgvector when the workspace chooses it


def required_kinds(index_type: str | None) -> tuple[str, ...]:
    """The connections an audit needs: the source and the vector index the workspace chose. The manifest is optional."""
    return ("s3", "pgvector") if (index_type or "qdrant").lower() == "pgvector" else ("s3", "qdrant")


def index_type_of(rows: dict[str, dict[str, Any]]) -> str:
    return str(((rows.get("index") or {}).get("config") or {}).get("type") or "qdrant")
CSV_ITEM = re.compile(r"^[A-Za-z0-9_.\-]{1,255}$")


# ---------------------------------------------------------------------------------------------- validation
def _clean(f: Field, raw: Any, allow_private: bool) -> Any:
    """Validate/normalise one submitted value. Returns None for 'unset'. Raises AccountError(422) with a readable message."""
    def bad(msg: str) -> AccountError:
        return AccountError(f"{f.label}: {msg}", 422)

    if raw is None:
        return None
    if f.type == "bool":
        if isinstance(raw, bool):
            return raw
        if str(raw).lower() in ("true", "1", "on", "yes"):
            return True
        if str(raw).lower() in ("false", "0", "off", "no", ""):
            return False
        raise bad("must be true or false")
    if f.type in ("int", "float"):
        if raw == "":
            return None
        try:
            v: Any = int(raw) if f.type == "int" else float(raw)
        except (TypeError, ValueError) as exc:
            raise bad("must be a number") from exc
        if (f.min is not None and v < f.min) or (f.max is not None and v > f.max):
            raise bad(f"must be between {f.min} and {f.max}")
        return v
    s = str(raw).strip()
    if s == "":
        return None
    if len(s) > f.max_len:
        raise bad(f"is too long (max {f.max_len} characters)")
    try:
        if f.type == "enum":
            if s not in f.choices:
                raise bad(f"must be one of {', '.join(f.choices)}")
        elif f.type == "url":
            assert_public_url(s, allow_private)
        elif f.type == "pgurl":
            validate_postgres_url(s, allow_private)
        elif f.type == "json":
            try:
                obj = json.loads(s)
            except json.JSONDecodeError as exc:
                raise bad(f"is not valid JSON ({exc.msg})") from exc
            if not isinstance(obj, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in obj.items()):
                raise bad('must be a JSON object of text values, e.g. {"document_id": "doc_ref"}')
            s = json.dumps(obj, separators=(",", ":"))
        elif f.type == "ident":
            check_identifier(s, f.label)
        elif f.type == "regex":
            try:
                rx = re.compile(s)
            except re.error as exc:
                raise bad(f"is not a valid regular expression ({exc})") from exc
            if "document_id" not in rx.groupindex:
                raise bad("must contain a (?P<document_id>...) group")
        elif f.type == "csv":
            items = [p.strip() for p in s.split(",") if p.strip()]
            if not all(CSV_ITEM.match(p) for p in items):
                raise bad("may only contain letters, digits, '_', '-', '.' separated by commas")
            s = ",".join(items)
    except UnsafeTarget as exc:
        raise bad(str(exc)) from exc
    except ValueError as exc:  # check_identifier
        raise bad(str(exc)) from exc
    return s


def apply_values(kind: str, config: dict[str, Any], secrets: dict[str, Any], values: dict[str, Any], allow_private: bool) -> tuple[dict, dict]:
    """Merge submitted values over the stored ones. Secret fields: omitted/null keeps the stored value, "" clears it."""
    spec = SPECS[kind]
    known = {f.name for f in spec.fields}
    extra = set(values) - known
    if extra:
        raise AccountError(f"Unknown setting(s): {', '.join(sorted(extra))}", 422)
    cfg, sec = dict(config), dict(secrets)
    for f in spec.fields:
        if f.name not in values:
            continue
        raw = values[f.name]
        if f.secret:
            if raw is None:
                continue
            if isinstance(raw, str) and raw.strip() == "":
                sec.pop(f.name, None)
                continue
            sec[f.name] = _clean(f, raw, allow_private)
        else:
            v = _clean(f, raw, allow_private)
            if v is None:
                cfg.pop(f.name, None)
            else:
                cfg[f.name] = v
    return cfg, sec


def is_configured(kind: str, config: dict[str, Any], secrets: dict[str, Any]) -> bool:
    required = [f for f in SPECS[kind].fields if f.required]
    if not required:  # an optional group counts as configured only once something has actually been set
        return any(v not in (None, "") for v in (*config.values(), *secrets.values()))
    return all((secrets if f.secret else config).get(f.name) not in (None, "") for f in required)


# ---------------------------------------------------------------------------------------------- settings overlay
def overlay(base: Settings, rows: dict[str, dict[str, Any]]) -> Settings:
    """The engine Settings for one workspace. Anything the workspace did not set falls back to the *default*, never to
    the platform's environment, so one deployment's env can never leak into a user's connections."""
    defaults = Settings.model_fields
    # alert_email_to is the operator's own address (single-user modes): a workspace's emails go to the workspace's users only
    upd: dict[str, Any] = {"mode": "live", "audit_interval_minutes": 0, "public_base_url": None, "alert_email_to": None}
    for kind, spec in SPECS.items():
        data = rows.get(kind) or {"config": {}, "secrets": {}}
        for f in spec.fields:
            v = (data["secrets"] if f.secret else data["config"]).get(f.name)
            upd[f.setting] = v if v is not None else defaults[f.setting].default
    return base.model_copy(update=upd)


def guard_settings(settings: Settings, kind: str | None = None) -> None:
    """Re-check, right before connecting, that every target the user configured is a public host."""
    ap = settings.allow_private_hosts
    try:
        if kind in (None, "s3") and settings.s3_endpoint_url:
            assert_public_url(settings.s3_endpoint_url, ap)
        if kind in (None, "manifest") and settings.manifest_database_url:
            validate_postgres_url(settings.manifest_database_url, ap)
        if kind in (None, "qdrant") and settings.qdrant_url:
            assert_public_url(settings.qdrant_url, ap)
        if kind in (None, "pgvector") and settings.pgvector_database_url:
            validate_postgres_url(settings.pgvector_database_url, ap)
        if kind in (None, "repair") and settings.repair_webhook_url:
            assert_public_url(settings.repair_webhook_url, ap)
        if kind in (None, "alerts") and settings.alert_webhook_url:
            assert_public_url(settings.alert_webhook_url, ap)
    except UnsafeTarget as exc:
        raise ConnectorError(str(exc)) from exc


def _factory(settings: Settings) -> Connectors:
    missing = []
    if not (settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key):
        missing.append("S3 source documents")
    if settings.uses_pgvector:  # the manifest is optional: only S3 and the vector index are needed
        if not (settings.pgvector_database_url and settings.pgvector_table):
            missing.append("the pgvector index")
    elif not settings.qdrant_url:
        missing.append("the Qdrant index")
    if missing:
        raise SetupIncomplete("Finish setup first: connect " + ", ".join(missing) + " on the Data Sources page.")
    guard_settings(settings)
    return build_connectors(settings)


# ---------------------------------------------------------------------------------------------- manager
class WorkspaceManager:
    CACHE_MAX = 64

    def __init__(self, base: Settings, ledger: Ledger, accounts: Accounts) -> None:
        self.base, self.ledger, self.accounts = base, ledger, accounts
        self._cache: dict[str, tuple[str, IntegrityService]] = {}
        self._lock = threading.Lock()

    # ---- views
    def view(self, ws: str) -> dict[str, Any]:
        rows = self.accounts.load_settings(ws)
        kinds = []
        for kind, spec in SPECS.items():
            data = rows.get(kind) or {"config": {}, "secrets": {}, "updated_at": None, "last_test": None}
            fields = []
            for f in spec.fields:
                v = None if f.secret else data["config"].get(f.name)
                fields.append({"name": f.name, "label": f.label, "type": f.type, "secret": f.secret, "required": f.required,
                               "help": f.help, "placeholder": f.placeholder, "choices": list(f.choices), "value": v,
                               "has_value": bool(data["secrets"].get(f.name)) if f.secret else v not in (None, "")})
            kinds.append({"kind": kind, "title": spec.title, "description": spec.description, "fields": fields,
                          "configured": is_configured(kind, data["config"], data["secrets"]),
                          "updated_at": iso(data["updated_at"]) if data.get("updated_at") else None,
                          "last_test": data.get("last_test"), "required_for_audit": kind in REQUIRED_KINDS})
        configured = {k["kind"]: k["configured"] for k in kinds}
        needed = required_kinds(index_type_of(rows))
        for k in kinds:
            k["required_for_audit"] = k["kind"] in needed
        missing = [k for k in needed if not configured[k]]
        return {"kinds": kinds, "ready": not missing, "missing": missing, "index_type": index_type_of(rows)}

    def is_ready(self, ws: str) -> bool:
        rows = self.accounts.load_settings(ws)
        return all(is_configured(k, (rows.get(k) or {}).get("config", {}), (rows.get(k) or {}).get("secrets", {}))
                   for k in required_kinds(index_type_of(rows)))

    # ---- changes
    def save(self, ws: str, kind: str, values: dict[str, Any]) -> dict[str, Any]:
        if kind not in SPECS:
            raise AccountError("Unknown settings group.", 404)
        rows = self.accounts.load_settings(ws).get(kind, {"config": {}, "secrets": {}})
        cfg, sec = apply_values(kind, rows["config"], rows["secrets"], values, self.base.allow_private_hosts)
        self.accounts.save_settings(ws, kind, cfg, sec)
        self.invalidate(ws)
        return self.view(ws)

    def invalidate(self, ws: str) -> None:
        with self._lock:
            self._cache.pop(ws, None)

    # ---- the per-workspace service
    def settings_for(self, ws: str) -> Settings:
        return overlay(self.base, self.accounts.load_settings(ws))

    def service(self, ws: str) -> IntegrityService:
        version = self.accounts.settings_version(ws)
        with self._lock:
            hit = self._cache.get(ws)
            if hit and hit[0] == version:
                return hit[1]
        svc = IntegrityService(self.settings_for(ws), self.ledger.for_workspace(ws), connector_factory=_factory, init_schema=False)
        svc._guard = guard_settings
        with self._lock:
            if len(self._cache) >= self.CACHE_MAX:
                self._cache.pop(next(iter(self._cache)))
            self._cache[ws] = (version, svc)
        return svc

    # ---- connection tests (run the REAL connectors against the user's infrastructure)
    def test(self, ws: str, kind: str, values: dict[str, Any] | None = None) -> dict[str, Any]:
        if kind not in SPECS:
            raise AccountError("Unknown settings group.", 404)
        rows = self.accounts.load_settings(ws)
        data = rows.get(kind) or {"config": {}, "secrets": {}}
        cfg, sec = apply_values(kind, data["config"], data["secrets"], values or {}, self.base.allow_private_hosts)
        settings = overlay(self.base, {**rows, kind: {"config": cfg, "secrets": sec}})
        checks: list[dict[str, str]]
        try:
            if not is_configured(kind, cfg, sec):
                raise ConnectorError("Fill in the required fields first: " + ", ".join(
                    f.label for f in SPECS[kind].fields if f.required and (sec if f.secret else cfg).get(f.name) in (None, "")))
            guard_settings(settings, kind)
            checks = self._diagnose(kind, settings)
        except ConnectorError as exc:
            checks = [{"name": "Configuration", "status": "fail", "detail": str(exc)}]
        except Exception as exc:  # a test must report problems, never crash
            checks = [{"name": "Connection", "status": "fail", "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}]
        result = {"ok": all(c["status"] != "fail" for c in checks), "tested_at": iso(utcnow()), "checks": checks}
        if values is None:  # only a test of the *saved* settings is remembered
            self.accounts.set_last_test(ws, kind, result)
        return result

    @staticmethod
    def _diagnose(kind: str, settings: Settings) -> list[dict[str, str]]:
        if kind == "s3":
            from .connectors.s3 import S3Source

            return S3Source(settings, fast=True).diagnose()
        if kind == "manifest":
            from .connectors.postgres import PostgresManifest

            m = PostgresManifest(settings)
            try:
                return m.diagnose()
            finally:
                m.engine.dispose()
        if kind == "qdrant":
            from .connectors.qdrant import QdrantIndex

            return QdrantIndex(settings, fast=True).diagnose()
        if kind == "pgvector":
            from .connectors.pgvector import PgVectorIndex

            idx = PgVectorIndex(settings, fast=True)
            try:
                return idx.diagnose()
            finally:
                idx.engine.dispose()
        return [{"name": "Settings", "status": "ok", "detail": "valid"}]
