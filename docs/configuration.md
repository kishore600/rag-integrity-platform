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

Set `RAGI_S3_LOOKUP_FROM_MANIFEST=true` for a very large bucket: the audit then reads exactly the files named by the manifest's
`source_uri` column (one HEAD request each, only keys matching `RAGI_S3_KEY_PATTERN`) instead of listing every object. Files that
are in S3 but not in the manifest are not discovered in this mode.

Set `RAGI_SOURCE_DOCUMENTS_ONLY=true` when the manifest or the vector index is shared with more than the bucket covers: the
S3 inventory (chosen by `RAGI_S3_KEY_PATTERN`) then defines the corpus, other manifest rows and vectors are ignored, and only
the matching points are read from Qdrant with a server-side filter. Left-over-vector findings are not produced in this mode.

**Large indexes, checkpoints and resuming.** With that setting on, the vector index is read for a slice of documents at a time (`RAGI_AUDIT_SLICE_DOCUMENTS`, default 5000). Each finished slice is recorded at once, so an audit that stops part-way (a timeout, a cluster that stays unreachable, a killed serverless function) ends `partial` with everything before the stop already reported, and `ragi audit --resume` (or `POST /api/audits {"resume": true}`) continues after the last checkpoint. Requests that fail for a reason that can pass (timeouts, rate limits, HTTP 5xx) are retried with backoff first. An incomplete scan never reports a document as missing. See GUIDE.md 3.12.

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

**The manifest is optional.** Leave `RAGI_MANIFEST_DATABASE_URL` unset and the audit compares your S3 files with the vector index directly (it needs a `source_hash` on every vector to recognise a changed file). With a manifest it can also check what the pipeline claimed. See GUIDE.md 3.15.

**pgvector instead of Qdrant.** Set `RAGI_INDEX_TYPE=pgvector`, `RAGI_PGVECTOR_DATABASE_URL` (a role that can only SELECT) and `RAGI_PGVECTOR_TABLE`; `RAGI_PGVECTOR_COLUMN_MAP` points our names at your columns or at a key inside a JSON column (`{"document_id": "cmetadata.doc_id"}`). `RAGI_PGVECTOR_DISTANCE` is `cosine`, `l2` or `inner_product`. See GUIDE.md 3.16.

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

* **Notifications and email**: after every audit that finishes, a notification is added under the bell, each with its next-step buttons (Resume audit, Run it again, Review the issues, Verify deletions), and an email with the same content is sent when `RAGI_ALERT_EMAIL_WHEN` allows it (`always`, `attention` or `never`). Email needs the mail account: `RAGI_SMTP_HOST` and `RAGI_SMTP_FROM` (plus `RAGI_SMTP_PORT`, `RAGI_SMTP_USER`, `RAGI_SMTP_PASSWORD`, `RAGI_SMTP_SECURITY`), `RAGI_ALERT_EMAIL_TO` in single-user modes (app mode emails each workspace's own users), and `RAGI_APP_URL` for the links. See GUIDE.md 3.14.
* **Email a repair plan**: a person can email a plan (summary, CSV and the exact worker payload) from the plan panel. It is sent only
  when someone presses **Email plan**; there is no scheduled or automatic mail. In single-user modes it goes out through the same mail
  account as the audit alerts (`RAGI_SMTP_*`); to use another server set `RAGI_PLAN_MAIL_HOST` and `RAGI_PLAN_MAIL_FROM` (plus
  `RAGI_PLAN_MAIL_PORT`, `RAGI_PLAN_MAIL_SECURITY`, `RAGI_PLAN_MAIL_USERNAME`, `RAGI_PLAN_MAIL_PASSWORD`). In app mode the platform's
  account is never used: each workspace fills in its own **Email** settings, a public mail server on port 25, 465, 587 or 2525, always encrypted.
