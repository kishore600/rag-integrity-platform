# Configuration reference

All settings are environment variables with the `RAGI_` prefix (or entries in a local `.env`). See `.env.example` for the
full annotated list. This page explains the parts that need judgement.

## Source documents (S3)

`RAGI_S3_KEY_PATTERN` is a regex applied to the object key (after `RAGI_S3_PREFIX`). It must have a
`(?P<document_id>...)` group and may have `(?P<tenant_id>...)`. Default: `^(?P<tenant_id>[^/]+)/(?P<document_id>.+)$`, i.e.
`acme/policies/leave.pdf` -> tenant `acme`, document `policies/leave.pdf`. Single-tenant bucket:
`RAGI_S3_KEY_PATTERN=^(?P<document_id>.+)$` and `RAGI_S3_DEFAULT_TENANT=main`.

Scoped audits (verify a handful of documents) rebuild the key as `<prefix><tenant>/<document>`, so keep that layout or
use a tenant-less pattern.

### Choosing `RAGI_S3_HASH_MODE`

| Mode | How the content hash is obtained | Cost | When |
|---|---|---|---|
| `metadata` (default) | `x-amz-meta-sha256` (key configurable) or S3's additional `ChecksumSHA256`; falls back to the ETag (flagged) | 1 HEAD / object | you control uploads and can store a sha256 |
| `compute` | streams the object and hashes it here (contents are discarded) | egress + time | you cannot change uploads; correctness first |
| `etag` | the ETag | none beyond the listing | quick start. **Multipart ETags are not content hashes**; such documents are marked `hash_reliable=false` and stale findings drop to medium |

Whatever you choose, the pipeline must record the **same** value as `source_hash` in the manifest and in each vector's
payload, otherwise every document will look stale.

## Processing manifest (PostgreSQL / Supabase)

Table and schema: `RAGI_MANIFEST_TABLE`, `RAGI_MANIFEST_SCHEMA`. Missing optional columns are simply skipped;
only `document_id` is mandatory. Map your own column names with JSON:

```
RAGI_MANIFEST_COLUMN_MAP={"document_id":"doc_ref","processing_status":"state","source_hash":"content_sha256"}
```

Canonical columns: `tenant_id, document_id, source_uri, source_version, source_hash, parsed_hash, parser_version,
chunking_version, chunk_size, chunk_overlap, embedding_model, embedding_model_version, embedding_dim, preprocessing,
expected_chunk_count, indexed_chunk_count, indexed_version, processing_status, last_verified_at, updated_at, acl_hash`.

Add `RAGI_MANIFEST_CHUNK_TABLE` (columns `tenant_id, document_id, chunk_id, chunk_index, chunk_hash`) to learn *which*
chunks are missing. Status values recognised: success-like (`success, indexed, completed, done, ready, ok, processed, true`;
`true` lets a boolean `is_indexed` column be mapped as the status), in-flight (`pending, queued, processing, running,
indexing, ...`), failed-like (`failed, error`), deleted (`deleted, tombstoned`).

Set `RAGI_SOURCE_DOCUMENTS_ONLY=true` when the manifest or the vector index is shared with more than the bucket covers: the
S3 inventory (chosen by `RAGI_S3_KEY_PATTERN`) then defines the corpus, other manifest rows and vectors are ignored, and only
the matching points are read from Qdrant with a server-side filter. Left-over-vector findings are not produced in this mode.

Use a database role that can only `SELECT`; the connector additionally opens every transaction `READ ONLY`.

## Vector index (Qdrant)

Each point's payload should carry: `tenant_id`, `document_id`, `chunk_id`, `chunk_index`, `source_hash` (same value as
above), and ideally the pipeline fingerprint (`parser_version, chunking_version, chunk_size, chunk_overlap,
embedding_model, embedding_dim, preprocessing`) and `acl_hash`. If your payload uses other names or nesting:

```
RAGI_QDRANT_PAYLOAD_MAP={"document_id":"doc_id","tenant_id":"meta.tenant","source_hash":"meta.sha256"}
```

`RAGI_QDRANT_COLLECTIONS` lists the collections to audit; empty means all. Multi-tenant deployments that shard
tenants over collections work as-is. `RAGI_QDRANT_CHECK_VECTORS=true` also fetches vectors to find empty/all-zero
embeddings (slower, more memory on the Qdrant side). Named vectors: `RAGI_QDRANT_VECTOR_NAME`.

Required payload fields default to `document_id` and `source_hash` (plus `tenant_id` once more than one tenant exists);
override with `RAGI_REQUIRED_PAYLOAD_FIELDS`.

## Target fingerprint

`RAGI_TARGET_*` describes how documents **should** currently be processed. A vector whose recorded fingerprint conflicts
with it (where both sides know a value) is classed `outdated`. Without a target, only mixed configurations inside one
document are reported. Setting `RAGI_TARGET_EMBEDDING_DIM` also checks every collection's vector size.

## Severity at a glance

`critical`: pipeline claimed success but data is missing/partial; deleted content that is actually retrievable; cross-tenant
vectors; collection dimension mismatch. `high`: missing/stale/empty embeddings, orphans, ACL mismatch, embedding-model
drift. `medium`: duplicates, superseded vectors, chunking drift, count mismatches, suspected gaps. `low`: bookkeeping.

## Operations

* **Scheduling**: `RAGI_AUDIT_INTERVAL_MINUTES=30` runs audits inside the server, or call `ragi audit --fail-on high` from cron/CI.
  Overlapping audits are refused (HTTP 409) rather than queued.
* **Alerts**: `RAGI_ALERT_WEBHOOK_URL` (Slack incoming-webhook compatible). Only *new*, *reopened* or *escalated* issues at or
  above `RAGI_ALERT_MIN_SEVERITY` are sent, so a steady state is silent.
* **Cost estimates**: `RAGI_EMBEDDING_PRICE_PER_MTOK` and `RAGI_CHUNK_SIZE_TOKENS` feed the reindex recommendations.
