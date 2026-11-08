# RAG Integrity: the complete guide

This is the full reference for everything that was built: what it is, how it works, every screen, every Settings field, every
issue it can raise, every API endpoint and command, the data it stores, how it is secured and deployed, and what was and was not
verified. The tables of settings, endpoints, commands, environment variables and database columns were extracted from the code,
and `tests/test_docs.py` fails if this file drifts from the code.

**Contents**
1. [What it is](#1-what-it-is)
2. [What was built](#2-what-was-built)
3. [How it thinks: the mental model](#3-how-it-thinks-the-mental-model)
4. [The dashboard, tab by tab](#4-the-dashboard-tab-by-tab)
5. [Settings: every group and every field](#5-settings-every-group-and-every-field)
6. [Issue types: what each one means](#6-issue-types-what-each-one-means)
7. [The repair workflow](#7-the-repair-workflow)
8. [Impact and cost, blast radius, reports](#8-impact-and-cost-blast-radius-reports)
9. [HTTP API reference](#9-http-api-reference)
10. [Command line reference](#10-command-line-reference)
11. [Environment variables](#11-environment-variables)
12. [Data model: what is stored](#12-data-model-what-is-stored)
13. [Security model](#13-security-model)
14. [Deployment and operations](#14-deployment-and-operations)
15. [Verification status](#15-verification-status)
16. [Limits and caveats](#16-limits-and-caveats)
17. [Lessons learned while building](#17-lessons-learned-while-building)
18. [Glossary](#18-glossary)

---

## 1. What it is

**One sentence:** RAG Integrity tells you when your RAG (retrieval-augmented generation) index is wrong, before your users do.

**The problem.** A RAG system stores your documents as vectors in a vector database. Many things can silently go wrong while every
background job reports "success": some documents are never embedded; updated documents keep their old vectors; deleted documents
stay searchable; only some chunks of a document are indexed; retries create duplicates; permissions metadata drifts; the embedding
model or chunking strategy changes but old documents are not reprocessed. The application keeps running and users get incomplete,
outdated or wrong answers without any error.

**What the product does.** It is an *independent verifier* that sits beside your pipeline. It reads three things through read-only
connectors, compares them, and records every disagreement with evidence:

| Source | System | What it represents |
|---|---|---|
| **Source documents** | S3 (or an S3-compatible store) | what *exists* right now |
| **Processing manifest** | PostgreSQL / Supabase table | what your pipeline *believes it did* |
| **Vector index** | Qdrant | what is actually *searchable* |

**What it deliberately does not do:** it does not parse documents, create embeddings, host a vector database, or run a chatbot. It
never writes to or deletes from your systems. Repairs are handed to **your own** worker through a signed webhook, and the platform
then verifies the result independently.

**Who it is for.** Teams running a production RAG pipeline over S3 + Postgres + Qdrant who need to know whether the index is
trustworthy, which exact documents are wrong, why, and what it will cost to fix.

---

## 2. What was built

### 2.1 The running pieces

| Piece | Where | Purpose |
|---|---|---|
| **Live web app** | https://rag-integrity-platform.vercel.app | the multi-user product: sign up, connect your own infrastructure, audit, repair |
| **Vercel project** | `rag-integrity-platform`, team `kishore600s-projects` (Hobby) | hosts the app as one FastAPI serverless function |
| **Supabase project** | `rag-integrity` (ref `uyoewjceiiwlmmhsdlga`, region ap-northeast-2) | accounts, sessions, encrypted connection secrets, and the ledger (13 tables in the private `ragi` schema) |
| **GitHub repository** | `kishore600/rag-integrity-platform` (private) | source code, CI, and the Vercel auto-deploy trigger |
| **CI** | GitHub Actions | runs the tests on Python 3.10 and 3.12 against a real Postgres, a real Qdrant server and S3 over HTTP; builds the Docker image and publishes it to GHCR |

Your S3 bucket, manifest table and Qdrant cluster are **not** part of the product: each user connects their own.

### 2.2 The code, module by module (`src/ragintegrity/`)

| Module | Lines | What it does |
|---|---|---|
| `models.py` | 214 | the vocabulary: `SourceDoc`, `ManifestRow`, `IndexedChunk`, `Fingerprint`, `Finding`, `DocSummary`, `Scope`; enums for issue types, severities, actions |
| `config.py` | 150 | every `RAGI_*` setting (pydantic-settings), identifier validation |
| `connectors/s3.py` | 216 | read-only S3 inventory, hash modes, key parsing, `diagnose()` for the connection test |
| `connectors/postgres.py` | 253 | read-only manifest reader (READ ONLY transactions, column mapping), `diagnose()` |
| `connectors/qdrant.py` | 188 | read-only vector scan (scroll), retrieval probe, `diagnose()` |
| `connectors/payload.py` | 79 | maps a Qdrant payload to the canonical chunk record (supports dotted paths) |
| `connectors/factory.py`, `base.py` | 57 | connector contracts and the demo/live factory |
| `engine/index_state.py` | 152 | classifies every vector as it is scanned (fresh / stale / outdated / unknown / orphan) |
| `engine/reconcile.py` | 559 | the reconciliation engine: compares source vs manifest vs index and emits findings |
| `engine/retrieval.py` | 58 | retrieval probes: can the bad content actually be returned by a search? |
| `engine/audit.py` | 121 | pulls the three inventories, enforces the time budget, runs the engine |
| `engine/planning.py` | 100 | turns issues into per-document repair items and estimates the work and cost |
| `engine/blast.py` | 117 | blast-radius analysis |
| `ledger.py` | 659 | the workspace-scoped store of issues, documents, runs, plans, and the account tables (SQLite locally, Postgres/Supabase in production) |
| `service.py` | 267 | the one object the API/CLI use: audits, locking, overview, inspection, friendly errors |
| `repair.py` | 206 | plan, signed webhook, independent verification, approved cleanup |
| `alerts.py`, `report.py` | 115 | Slack-compatible alerts; markdown/CSV/JSON integrity report |
| `security.py` | 170 | password hashing, the secret vault, SSRF guard, credential scrubbing |
| `accounts.py` | 242 | users, sessions, rate limits, API keys, encrypted per-workspace settings |
| `workspaces.py` | 374 | the declarative Settings specification, validation, per-workspace service, connection tests |
| `api/app.py` | 548 | the HTTP API and authentication |
| `api/static/` | 968 | the dashboard (`index.html`, `app.js` 729 lines, `styles.css`), no framework, no build step |
| `cli.py` | 194 | the `ragi` command |
| `demo/` | 501 | a synthetic world with 47 injected faults, a toy pipeline, seeding for real infrastructure (local exploration and tests only) |

Also: `api/index.py` (the Vercel entrypoint), `examples/reference_worker/worker.py` (a runnable receiver for the repair webhook),
`supabase/migrations/` (2 migrations, 328 lines of SQL), `scripts/vercel-env.ps1` and `scripts/seed_live.py`, `Dockerfile`,
`docker-compose.yml`, `.github/workflows/ci.yml`, and `docs/`.

**Size:** about 5,500 lines of Python in `src`, 2,050 lines of tests, 729 lines of dashboard JavaScript, 328 lines of SQL.

### 2.3 The three ways it can run

| Mode (`RAGI_MODE`) | Who it is for | Accounts | Connections come from |
|---|---|---|---|
| `app` | **the hosted product**, or self-hosting it for several users | sign-up / login | each user's own *Settings* (encrypted in the database) |
| `live` | one team, one set of infrastructure | none (optional `RAGI_API_KEY`) | environment variables |
| `demo` | exploring locally | none | a built-in synthetic corpus with injected faults |

The live site runs `app` mode. Demo mode never runs on it.

---

## 3. How it thinks: the mental model

### 3.1 Three inventories, one key
Documents are identified by `(tenant_id, document_id)`. For each key the engine looks at what the **source** says, what the
**manifest** says, and what the **index** holds, and decides whether they agree.

### 3.2 Every vector gets a class
While the index is scanned, each vector is classified against the live source and your target pipeline:

| Class | Meaning |
|---|---|
| `fresh` | its `source_hash` (or version) matches the live source **and** its pipeline fingerprint matches your target |
| `stale` | its hash/version differs from the live source: it describes an older version of the document |
| `outdated` | content is current, but it was built with a different parser / chunker / embedding config than your target |
| `unknown` | the payload carries no hash or version, so freshness cannot be established from the index alone |
| `orphan` | the document no longer exists in the source |

### 3.3 Document status and the health score
| Status | Meaning |
|---|---|
| `healthy` | no findings |
| `degraded` | only medium or low findings |
| `broken` | at least one high or critical finding |
| `orphaned` | not in the source, but vectors still exist |
| `pending` | modified or being processed within the grace period, so not judged yet |

**Health score** = (healthy + pending documents) ÷ all documents, shown as a percentage. Green at 95% and above, amber at 80% and
above, red below.

### 3.4 What an audit does, step by step
1. Take a lock: **one audit at a time per workspace**, enforced by a database index (so it holds across serverless instances). A run
   that crashed and has been "running" for over 15 minutes is retired automatically.
2. Read the **source inventory** from S3 (keys, sizes, modified times, content hashes).
3. Read the **manifest rows** (and the chunk manifest if configured).
4. **Scan the vector index** page by page, classifying every point as above. Memory stays proportional to the corpus, not to scan buffers.
5. **Reconcile**: run the per-document checks and emit findings.
6. **Retrieval probes** (up to 25 per audit): for findings about content that should not be searchable, query the live index with one
   affected chunk's own vector, filtered to the owning tenant, and record the rank. A confirmed probe escalates severity.
7. **Apply to the ledger**: new problems become issues, previously known ones are updated, ones no longer seen are resolved, regressions
   are reopened. Per-document state is refreshed.
8. **Alert** (if configured) about *new, reopened or escalated* issues at or above the minimum severity.
9. Record the run with its statistics and duration.

**Time budget on Vercel:** an audit that has not finished within about 50 seconds stops with a clear message instead of being killed
(audit one tenant at a time, or run `ragi audit` elsewhere).

### 3.5 Scopes
An audit can cover everything, one **tenant**, or specific **documents**. Scoped audits are how repairs are verified. A scoped audit
only ever resolves issues inside its own scope.

### 3.6 The grace period
A document modified within the grace period (default 10 minutes), or whose manifest status is "in flight" and was updated within it,
is `pending`, not broken: it is probably still being ingested. A job stuck "processing" for longer than the grace period is flagged.

### 3.7 Issue lifecycle
An issue's id is a hash of *(type, tenant, document, collection)*, so the same problem is the **same row** across audits:
`occurrences` counts how often it was seen. `open` becomes `resolved` when an audit covering the document no longer finds it, and
returns to `open` (with `reopened_count` incremented) if it regresses. `ignored` is sticky and keeps your reason. Every change is a
row in `issue_events`.

### 3.8 Recognised manifest status values
The engine treats these `processing_status` values (case-insensitive) as: **success** - `success, succeeded, indexed, completed,
complete, done, ready, ok, processed`; **in flight** - `pending, queued, processing, running, in_progress, indexing, parsing,
embedding`; **failed** - `failed, error, errored, failure`; **deleted** - `deleted, tombstoned, removed`.

---

## 4. The dashboard, tab by tab

After signing in, the left menu has seven tabs. The header has **Run audit**, your email (opens *Account*), and a **Workspace**
badge. When setup is incomplete a banner says so and links to Settings, and Settings shows a `!`.

### Sign-in and Create account
One screen with two modes. Email plus password; the password must be at least 10 characters, not a common password, not one
repeated character, and must not contain your email name. Errors never reveal whether an email is registered (except that sign-up
says an email is taken). Closed sign-up shows "Registration is closed on this server."

### Overview
The answer to "is my index consistent with the source?"
- **Index health**: the health score ring and "N of M documents match the latest source exactly", the time of the last full audit,
  vectors scanned and duration. Buttons: *Review issues*, *Plan a repair*.
- **Health trend**: the score over the last 30 completed full audits.
- **Four counters**: open issues, critical, documents broken or orphaned, issues resolved so far.
- **Open issues by severity** and **by type** (bar charts).
- **Tenants**: documents, healthy count and a health bar per tenant. Clicking a tenant opens Documents filtered to it.
- With no audit yet it shows the **onboarding card** ("Connect your infrastructure" with the three required steps, or "Run your first audit" once connected).

### Issues
Every finding, worst first. Filters: **Status** (Open, Resolved, Ignored, All), **severity**, **type**, and search by document or title
(press Enter). Columns: *Severity, Issue, Document, Detail, Last seen*; 50 per page. Click a row for the detail panel:
- the severity, status and type, and the document (tenant plus path);
- the plain-language **detail** and the **Recommended action** (see section 6);
- a warning when **the pipeline reported success** for this document (job status alone would not have caught it);
- the **Retrieval probe**: whether the content is returned for a matching query, at what rank and score, with the top results and which are stale content;
- the **Problems** list for metadata findings; **Evidence** key/values; the **missing chunk** ids; the number of vectors that are removal candidates;
- the raw evidence (collapsible) and a **Timeline** (opened, severity changed, resolved, reopened, ignored);
- buttons: **Inspect document live**, **Ignore** (asks for a reason, kept in the audit trail) or **Reopen**.

### Documents
Document-level integrity. Filters: status (Broken, Degraded, Orphaned, Pending, Healthy), a tenant chip, and search by document id.
Columns: *Status, Document, Issues, Chunks (indexed / expected), Embedding model, Verified*. Buttons **Download report (.md)** and **CSV**
produce the document-level integrity report. Click a document for the live three-way view:
- three columns, fetched live from your systems: **Source (S3)**, **Manifest (Postgres)**, **Index (Qdrant)**;
- the **chunk grid**: one box per chunk, coloured *fresh, stale, outdated, unknown, orphan*, or a dashed red box for a chunk that is *missing from the index*; a number after the index means that chunk exists more than once;
- the **Findings** for this document and the pipeline fingerprints found in the index.

### Repairs
How problems get fixed safely (section 7). The top card creates a plan with a **Scope** (all open issues, medium and above, high and above, critical only) and an optional **Tenant**. Below is the list of plans. A plan page shows:
- a five-step stepper: **Plan, Reindex, Verify, Cleanup, Done**;
- four numbers: documents in the plan, chunks to regenerate, estimated embedding cost, and the saving compared with re-embedding everything;
- context buttons: **Trigger repair worker**, **Verify now**, **Re-trigger failed documents**, **Approve cleanup**, and **Preview payload** (the exact signed webhook body);
- a documents table with *Severity, Document, Actions, Status* and five verification boxes: *All expected chunks present, Embeddings present, Latest version indexed, Metadata correct, Old vectors inactive*;
- an **Activity** timeline.

### Impact & cost
- **Safe reindex recommendation**: how many documents need a full reindex, a chunk-level reindex, a metadata fix only (no embedding), and how many superseded vectors can be removed later; the targeted token cost compared with re-embedding the whole corpus, and the percentage saved.
- **Blast radius**: pick a scenario and press **Analyse**: *Current open issues*; *Pipeline config change* (enter an embedding model, chunking version or chunk size you plan to move to); or *Ingestion failure window* (the time the failure started). It returns documents and tenants affected, queries that touched them (from your retrieval log, last 14 days), the top affected documents by queries, and the re-embedding cost.

### Audit history
One chronological trail of audits (completed or failed, with trigger, findings and health), issue events, and repair events.

### Settings
Section 5. It starts with a checklist of the three required connections, then seven expandable groups, then API keys.

### Account (your email in the header)
Shows who you are signed in as, a **Change password** form (this signs out your other devices), and **Sign out**.

*Single-user modes (demo / live) replace Settings with a read-only **Connections** tab, show a demo banner and a **Reset demo** button in demo mode, and need no sign-in.*

---

## 5. Settings: every group and every field

Three groups are **required** before the first audit: S3, Manifest and Qdrant. The other four are optional tuning.
Every group is saved separately with **Save** (the three connections say **Save & test**: they save, then run the real connector and
remember the result). **Test without saving** checks what is typed in the form without storing it.

How secrets behave: a field marked **secret** is encrypted at rest, is **write-only** (after saving it shows "saved" and the value never
comes back), leaving it empty keeps the stored value, and **Remove** deletes it. Empty non-secret fields fall back to the default shown.
Every host or URL you enter must be a **public** address (section 13).

### 5.1 Source documents (S3)
Where your documents live. Read-only: `list` and `head`, plus `get` only in `compute` hash mode. Works with AWS S3 and S3-compatible
stores (Supabase Storage, MinIO, Cloudflare R2).

**Permissions.** On AWS, `HeadObject` is authorised by the `s3:GetObject` permission, so the key needs **both** `s3:ListBucket` (on the
bucket) and `s3:GetObject` (on its objects). Both are read-only and nothing is ever written. Only an `etag`-mode audit can run on
`s3:ListBucket` alone, and even then "Save & test" and repair verification still send HEAD requests.

**How to connect S3, step by step**
1. In AWS: *IAM > Users > Create user*, then attach this policy (replace `YOUR-BUCKET`):
   `{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::YOUR-BUCKET"},{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::YOUR-BUCKET/*"}]}`
2. Open that user's *Security credentials* tab, press *Create access key*, and copy the **Access key ID** and **Secret access key** (shown once).
3. Note the bucket's **region** (for example `ap-south-1`) from the S3 console.
4. In the app: sign in, open **Settings**, expand **Source documents (S3)** and fill **Bucket**, **Region**, **Access key ID** and **Secret access key**.
   Leave **Custom endpoint** empty for AWS.
5. Check how your keys look. The default **Key pattern** expects `tenant/path/to/document.pdf`. For a flat bucket with no tenants set it to
   `^(?P<document_id>.+)$`; to audit only a folder set **Key prefix**.
6. Press **Save & test**. Every line should say OK; a warning or failure names exactly what to change.
7. Make sure your pipeline records the **same SHA-256** that **Content hash** reads (the `sha256` user-metadata key by default) as
   `source_hash` in the manifest and in each Qdrant payload.

For an S3-compatible store set **Custom endpoint** to the provider's S3 URL (Supabase Storage: `https://<project-ref>.supabase.co/storage/v1/s3`)
and use that provider's region and access keys.

| Field | Required | Secret | Default | What it means and what it changes |
|---|---|---|---|---|
| **Bucket** | yes | no | none | The bucket to audit. |
| **Key prefix** | no | no | empty | Only keys under this prefix are audited. It is removed before the key pattern is applied, and scoped audits rebuild keys as `<prefix><tenant>/<document>`. |
| **Region** | no | no | none | The signing region (for example `us-east-1`). For S3-compatible stores use that provider's region (Supabase: your project's region). |
| **Custom endpoint** | no | no | none | Leave empty for AWS S3. For an S3-compatible store set its endpoint, for example `https://<ref>.supabase.co/storage/v1/s3`. When set, path-style addressing is used. Must be a public host. |
| **Access key ID** | yes | **yes** | none | The access key. Its user needs `s3:ListBucket` on the bucket **and** `s3:GetObject` on its objects (AWS authorises the HEAD requests that read hashes with `GetObject`). |
| **Secret access key** | yes | **yes** | none | The matching secret. |
| **Content hash** | no | no | `metadata` | How the content hash of each document is obtained. `metadata`: use the SHA-256 stored with the object (user-metadata key below, or S3's own SHA-256 checksum); one HEAD request per object, fast. `compute`: download each object and hash it here (always correct, costs egress and time; contents are discarded, never stored). `etag`: use the ETag; **multipart ETags are not content hashes**, so those documents are flagged "hash unreliable" and stale findings are downgraded to medium. |
| **SHA-256 metadata key** | no | no | `sha256` | The user-metadata key that holds the hex SHA-256 (case-insensitive). If an object has none, S3's `ChecksumSHA256` is used, then the ETag (flagged). |
| **Key pattern (regex)** | no | no | `^(?P<tenant_id>[^/]+)/(?P<document_id>.+)$` | Applied to each key (after the prefix). It **must** capture `(?P<document_id>...)` and may capture `(?P<tenant_id>...)`. With the default, `acme/policies/leave.pdf` is tenant `acme`, document `policies/leave.pdf`. Keys that do not match are ignored. For a single-tenant bucket use `^(?P<document_id>.+)$`. |
| **Default tenant** | no | no | `default` | The tenant used for keys when the pattern has no `tenant_id` group. |

**Important:** whatever hash you use here, your pipeline must record the **same value** as `source_hash` in the manifest and in each
Qdrant payload, otherwise every document will look stale.

**What "Save & test" checks (S3):** *Bucket reachable* (lists up to 200 keys under the prefix and explains common errors: no such bucket,
access denied, bad access key, wrong secret or region, unreachable endpoint); *Documents found*; *Key pattern* (how many sampled keys
match, with an example); *Object metadata* and *Content hashes* (how many of 5 sampled objects carry a SHA-256).

### 5.2 Processing manifest (PostgreSQL / Supabase)
The table your pipeline writes after processing each document. Read-only: **every query runs in a READ ONLY transaction** with a 45-second
statement timeout. Use a database role that can only `SELECT`.

| Field | Required | Secret | Default | What it means and what it changes |
|---|---|---|---|---|
| **Connection string** | yes | **yes** | none | `postgresql://user:password@host:5432/dbname?sslmode=require`. Must be a public host. Only `sslmode`, `connect_timeout` and `application_name` options are accepted (others are refused so a target cannot be smuggled in). Supabase's transaction pooler (port 6543) works. |
| **Schema** | no | no | `public` | The schema holding the tables. Letters, digits and underscores only. |
| **Document table** | no | no | `rag_document_manifest` | The table with one row per document. Same character rule. |
| **Chunk table (optional)** | no | no | none | A table with one row per expected chunk. With it, the audit can name **exactly which chunks are missing**; without it, partial indexes are detected from chunk counts and gaps in `chunk_index`. |
| **Column map (JSON)** | no | no | empty | Map our column names to yours, for example `{"document_id": "doc_ref", "processing_status": "state"}`. |
| **Chunk column map (JSON)** | no | no | empty | The same for the chunk table. |

**Manifest columns.** Only `document_id` is mandatory; any column your table lacks is simply skipped.

| Column | What it holds |
|---|---|
| `tenant_id` | the tenant (if absent, the default tenant is assumed) |
| `document_id` | the stable document identity (**required**) |
| `source_uri` | where the original lives |
| `source_version`, `source_hash` | the version and SHA-256 of the source **as your pipeline last processed it** |
| `parsed_hash` | hash of the extracted content |
| `parser_version`, `chunking_version`, `chunk_size`, `chunk_overlap`, `embedding_model`, `embedding_model_version`, `embedding_dim`, `preprocessing` | the pipeline fingerprint used for this document |
| `expected_chunk_count`, `indexed_chunk_count` | how many chunks the pipeline expected and believes it indexed |
| `indexed_version` | the version your pipeline marked as active in the index |
| `processing_status` | for example `success`, `failed`, `processing` (section 3.8) |
| `last_verified_at`, `updated_at` | timestamps (`updated_at` drives the grace period) |
| `acl_hash` | a hash of the document's permissions |

**Chunk table columns:** `tenant_id`, `document_id`, `chunk_id`, `chunk_index`, `chunk_hash`.

**What "Save & test" checks (manifest):** *Database reachable* (explains bad password, timeout, unresolved host, SSL); *Manifest table* (found, how many of the 21 columns are mapped); *Columns used for checks* (warns when `source_hash`, `processing_status`, `expected_chunk_count` or `indexed_chunk_count` are missing); *Rows* (up to 100,000+); *Role is read-only* (warns if your role can write); *Chunk manifest*.

### 5.3 Vector index (Qdrant)
Your vector store. Read-only: `scroll`, `retrieve` and `query`; nothing is written or deleted.

| Field | Required | Secret | Default | What it means and what it changes |
|---|---|---|---|---|
| **URL** | yes | no | none | For example `https://xyz.cloud.qdrant.io:6333`. A URL without a port uses 6333; if Qdrant sits behind a TLS reverse proxy add `:443`. Must be a public host. |
| **API key** | no | **yes** | none | A read-capable key. Leave empty for an open instance. |
| **Collections** | no | no | empty | Comma-separated collection names to audit. Empty means every collection. A document is expected in **at least one** of them. |
| **Payload field map (JSON)** | no | no | empty | If your payloads use other names, map them, for example `{"document_id": "doc_id", "tenant_id": "meta.tenant"}`. Dotted paths reach nested fields. |
| **Named vector** | no | no | none | Only if your collection uses named vectors. |
| **Detect empty embeddings** | no | no | off | Also fetch vectors to find points whose vector is missing, empty or all zeros. Slower and heavier for Qdrant. |

**Payload fields the engine reads:** `tenant_id`, `document_id`, `chunk_id`, `chunk_index`, `chunk_hash`, `source_hash`, `source_version`,
`parser_version`, `chunking_version`, `chunk_size`, `chunk_overlap`, `embedding_model`, `embedding_model_version`, `embedding_dim`,
`preprocessing`, `acl_hash`. At minimum put `document_id` and `source_hash` in every payload (plus `tenant_id` if you have several tenants).

**What "Save & test" checks (Qdrant):** *Qdrant reachable* (explains a rejected API key, timeout, unresolved host, refused connection);
*Collections* (names any missing one); *Collection <name>* (approximate point count and vector size) and *Payload of <name>* (samples
20 points and tells you whether `document_id` and `source_hash` are present), for up to the first 5 collections.

### 5.4 Target pipeline (optional)
How documents **should** currently be processed. A vector whose recorded configuration conflicts with this (where both sides know a
value) is classed `outdated` and reported as **pipeline drift**. Without a target, only mixed configurations inside one document are reported.

| Field | Default | Meaning |
|---|---|---|
| **Parser version** | none | for example `parser-2.1` |
| **Chunking version** | none | for example `recursive-v2` |
| **Chunk size**, **Chunk overlap** | none | whole numbers (size 1 to 1,000,000; overlap 0 to 1,000,000) |
| **Embedding model**, **Embedding model version** | none | for example `text-embedding-3-large` |
| **Embedding dimensions** | none | 1 to 65,536. **Also compared with every collection's vector size**: a mismatch is a critical collection-level finding. |
| **Preprocessing** | none | a label for your cleaning step |

A vector missing a fingerprint value in its payload inherits it from the manifest row.

### 5.5 Repair worker (optional)
Your own ingestion worker. The platform never writes to your systems: approved repairs are sent here as a signed webhook (section 7).

| Field | Secret | Default | Meaning |
|---|---|---|---|
| **Webhook URL** | no | none | Where the signed repair request is POSTed. Must be a public host. |
| **Signing secret** | **yes** | none | The shared HMAC-SHA256 key. Required before anything is sent; also verifies the worker's completion callback. |
| **Vector removal** | no | `manual` | `manual`: an operator must press **Approve cleanup** before vector removal is requested. `auto`: removal is requested immediately after verification passes. |

### 5.6 Alerts (optional)
| Field | Secret | Default | Meaning |
|---|---|---|---|
| **Webhook URL** | **yes** | none | A Slack-compatible incoming webhook (JSON with a `text` field). Treated as a secret because Slack webhook URLs are. |
| **Minimum severity** | no | `high` | `critical`, `high`, `medium` or `low`. Only **new, reopened or escalated** issues at or above it are sent, so a steady state is silent. |

### 5.7 Audit policy (optional)
| Field | Default | Meaning |
|---|---|---|
| **Grace period (minutes)** | 10 | 0 to 1,440. Documents modified or being processed within this window are `pending`, not broken. |
| **Default tenant** | `default` | Assumed when a Qdrant payload or manifest row has no tenant. |
| **Required payload fields** | empty | Comma-separated. Empty means `document_id` and `source_hash`, plus `tenant_id` once more than one tenant exists. A vector missing a required field raises a metadata finding. |
| **Embedding price (USD per 1M tokens)** | 0.13 | Used only for cost estimates. |
| **Tokens per chunk (for estimates)** | 512 | Used only for cost estimates. |

### 5.8 API keys
For CI, cron and sending retrieval logs. **Create key** with a name; the token (`ragi_...`) is shown **once**; only its hash is stored.
Use it as `Authorization: Bearer ragi_...`. A key acts only inside its workspace and can run audits and read results, but cannot read
settings, create keys or change passwords. Up to 20 keys per workspace; **Revoke** takes effect immediately. The page shows a ready-made
`curl` for scheduled audits.

### 5.9 Reference: all fields with internal names
| Group | UI label | Internal key | Env var (single-user modes) | Type |
|---|---|---|---|---|
| s3 | Bucket | `bucket` | `RAGI_S3_BUCKET` | text |
| s3 | Key prefix | `prefix` | `RAGI_S3_PREFIX` | text |
| s3 | Region | `region` | `RAGI_S3_REGION` | text |
| s3 | Custom endpoint | `endpoint_url` | `RAGI_S3_ENDPOINT_URL` | URL |
| s3 | Access key ID | `access_key_id` | `RAGI_S3_ACCESS_KEY_ID` | secret |
| s3 | Secret access key | `secret_access_key` | `RAGI_S3_SECRET_ACCESS_KEY` | secret |
| s3 | Content hash | `hash_mode` | `RAGI_S3_HASH_MODE` | metadata / compute / etag |
| s3 | SHA-256 metadata key | `sha256_metadata_key` | `RAGI_S3_SHA256_METADATA_KEY` | text |
| s3 | Key pattern (regex) | `key_pattern` | `RAGI_S3_KEY_PATTERN` | regex |
| s3 | Default tenant | `default_tenant` | `RAGI_S3_DEFAULT_TENANT` | text |
| manifest | Connection string | `database_url` | `RAGI_MANIFEST_DATABASE_URL` | Postgres URL, secret |
| manifest | Schema | `schema` | `RAGI_MANIFEST_SCHEMA` | identifier |
| manifest | Document table | `table` | `RAGI_MANIFEST_TABLE` | identifier |
| manifest | Chunk table (optional) | `chunk_table` | `RAGI_MANIFEST_CHUNK_TABLE` | identifier |
| manifest | Column map (JSON) | `column_map` | `RAGI_MANIFEST_COLUMN_MAP` | JSON |
| manifest | Chunk column map (JSON) | `chunk_column_map` | `RAGI_MANIFEST_CHUNK_COLUMN_MAP` | JSON |
| qdrant | URL | `url` | `RAGI_QDRANT_URL` | URL |
| qdrant | API key | `api_key` | `RAGI_QDRANT_API_KEY` | secret |
| qdrant | Collections | `collections` | `RAGI_QDRANT_COLLECTIONS` | comma list |
| qdrant | Payload field map (JSON) | `payload_map` | `RAGI_QDRANT_PAYLOAD_MAP` | JSON |
| qdrant | Named vector | `vector_name` | `RAGI_QDRANT_VECTOR_NAME` | text |
| qdrant | Detect empty embeddings | `check_vectors` | `RAGI_QDRANT_CHECK_VECTORS` | on/off |
| pipeline | Parser version | `parser_version` | `RAGI_TARGET_PARSER_VERSION` | text |
| pipeline | Chunking version | `chunking_version` | `RAGI_TARGET_CHUNKING_VERSION` | text |
| pipeline | Chunk size | `chunk_size` | `RAGI_TARGET_CHUNK_SIZE` | integer |
| pipeline | Chunk overlap | `chunk_overlap` | `RAGI_TARGET_CHUNK_OVERLAP` | integer |
| pipeline | Embedding model | `embedding_model` | `RAGI_TARGET_EMBEDDING_MODEL` | text |
| pipeline | Embedding model version | `embedding_model_version` | `RAGI_TARGET_EMBEDDING_MODEL_VERSION` | text |
| pipeline | Embedding dimensions | `embedding_dim` | `RAGI_TARGET_EMBEDDING_DIM` | integer |
| pipeline | Preprocessing | `preprocessing` | `RAGI_TARGET_PREPROCESSING` | text |
| repair | Webhook URL | `webhook_url` | `RAGI_REPAIR_WEBHOOK_URL` | URL |
| repair | Signing secret | `webhook_secret` | `RAGI_REPAIR_WEBHOOK_SECRET` | secret |
| repair | Vector removal | `cleanup_policy` | `RAGI_CLEANUP_POLICY` | manual / auto |
| alerts | Webhook URL | `webhook_url` | `RAGI_ALERT_WEBHOOK_URL` | URL, secret |
| alerts | Minimum severity | `min_severity` | `RAGI_ALERT_MIN_SEVERITY` | critical / high / medium / low |
| policy | Grace period (minutes) | `grace_minutes` | `RAGI_GRACE_MINUTES` | integer |
| policy | Default tenant | `default_tenant` | `RAGI_DEFAULT_TENANT` | text |
| policy | Required payload fields | `required_payload_fields` | `RAGI_REQUIRED_PAYLOAD_FIELDS` | comma list |
| policy | Embedding price (USD per 1M tokens) | `embedding_price_per_mtok` | `RAGI_EMBEDDING_PRICE_PER_MTOK` | number |
| policy | Tokens per chunk (for estimates) | `chunk_size_tokens` | `RAGI_CHUNK_SIZE_TOKENS` | integer |

In `app` mode a workspace's unset fields use the defaults above and **never** the server's environment, so one deployment's environment
cannot leak into a user's connections.

---

## 6. Issue types: what each one means

Severity runs `critical` > `high` > `medium` > `low` (> `info`). The **Recommended action** is what the Issues panel shows.

| Issue type | What it means | Exactly how it is detected | Severity | Recommended action |
|---|---|---|---|---|
| `missing_embedding` | A source document has no vectors at all. | The document exists in S3 and the index holds zero points for it (and it is not within the grace period). | **high**; **critical** if the manifest claims success (a success-like status, or `indexed_chunk_count` above 0): the pipeline reported success but wrote nothing. | `reindex_full` |
| `partial_index` | Only some of the expected chunks are indexed. | Compared per collection: **exact chunk ids** from the chunk table; else the manifest's `expected_chunk_count`; else **gaps in `chunk_index`** (a "suspected" finding). Skipped if the document is stale. | **high**; **critical** if the pipeline claims success; **medium** when only index gaps suggest it. | `reindex_chunks` |
| `stale_embedding` | The source changed but the vectors describe an older version. | All live vectors have a `source_hash` (or version) different from the source; or the payloads carry neither and the manifest's `source_hash` differs from the source. | **high**; **medium** when the source hash is an unreliable multipart ETag. Not raised during the grace period. | `reindex_full` |
| `superseded_active` | The latest version is indexed, but old-generation vectors still answer queries. | Fresh vectors exist **and** stale (older version) or outdated (older pipeline config) vectors also exist. | **medium**; **high** when a probe shows the old content is returned. | `cleanup_vectors` (after verification) |
| `orphan_vector` | A document was deleted at the source but its vectors remain searchable. | Vectors exist for a document that is not in the source, and that id exists under no other tenant. | **high**; **critical** when a probe shows it is returned for a matching query. | `cleanup_vectors` |
| `duplicate_chunk` | The same chunk is indexed more than once (typically retried jobs). | Two or more live points share a chunk key (chunk id, else chunk index) in the same collection. The first-seen copy is kept; the rest are removal candidates. | **medium** | `cleanup_vectors` |
| `metadata_inconsistent` | The manifest, payloads, ACL or versions disagree. | One finding per document listing its *problems* (below); there is also a collection-level problem for vectors with no document id. | the **highest** problem's severity | `fix_metadata` (collection-level: `investigate`) |
| `pipeline_drift` | Indexed with a different parser, chunker or embedding setup than your target. | (1) a document whose live content is current but all vectors conflict with the target; (2) a document whose live vectors disagree among themselves; (3) the target embedding dimension differs from a collection's vector size. | **high** if the embedding model, its version or the dimensions differ; **medium** for chunking/parser/preprocessing; **critical** for the collection-level dimension mismatch | `reindex_full` (collection-level: `investigate`) |
| `empty_embedding` | A point exists but its vector is missing, empty or all zeros, so it can never match a query. | Requires "Detect empty embeddings" (vectors are fetched). | **high** | `reindex_full` |
| `tenant_mismatch` | Vectors are tagged with the wrong tenant: a cross-tenant leak risk. | Vectors exist under tenant X for a document that does not exist in X but does exist in another tenant. | **critical** | `cleanup_vectors` |
| `manifest_orphan` | A manifest row exists for a document that is gone from both the source and the index. | Row present, no source, no vectors, status not `deleted/tombstoned/removed`. | **low** | `investigate` |

**Metadata problems** (inside `metadata_inconsistent`): `missing_payload_fields` (medium: vectors lack required fields),
`untracked_in_manifest` (medium: vectors for a current document but no manifest row), `manifest_count_mismatch` (medium: manifest says
N chunks indexed but the index holds a different number; suppressed when `partial_index` already explains it), `acl_mismatch` (**high**:
vectors carry a different ACL hash than the manifest, so permissions may be wrong at query time), `manifest_lags_index` (low: the index is
current but the manifest records an older hash), `manifest_version_mismatch` (low), `status_failed_but_indexed` (low), and
`unattributed_vectors` (high, collection-level: points with no document id).

**Recommended actions:** `reindex_full` re-process the whole document; `reindex_chunks` re-embed only the missing chunks;
`cleanup_vectors` remove superseded vectors, only after replacements are verified; `fix_metadata` correct the manifest or payload
(no re-embedding); `investigate` needs a human.

---

## 7. The repair workflow

The platform holds **read-only** access and never deletes vectors blindly. Repair is a hand-off with independent verification.

1. **Plan.** Open issues are grouped per document into the *smallest safe action*: `reindex_full` for missing, stale, drifted or empty-embedding documents; `reindex_chunks` for partial indexes; `fix_metadata` when only metadata is wrong; and a "cleanup later" flag for superseded, duplicate, orphan and tenant-mismatch vectors. Collection-level findings are not document repairs.
2. **Trigger.** The reindex request is POSTed to your webhook, signed with HMAC-SHA256 over `"<timestamp>.<raw body>"` (headers `X-Ragi-Event`, `X-Ragi-Timestamp`, `X-Ragi-Signature`, `X-Ragi-Delivery`; a 5-minute replay window). **Reindex phase: add or replace only, never delete.** Without a signing secret nothing is sent.
3. **Your worker** re-reads the latest source, parses, chunks, embeds and upserts with deterministic point ids (retries overwrite instead of duplicating), updates the manifest, and optionally calls back to the platform.
4. **Verify.** A scoped re-audit of the plan's documents runs and each document gets five checks: *all expected chunks present*, *embeddings present*, *latest version indexed*, *metadata correct*, *old vectors inactive*. A worker that reports success but wrote half the chunks fails here, and its documents keep their old vectors.
5. **Approve cleanup.** With policy `manual` an operator presses **Approve cleanup**; with `auto` this happens after verification. The removal list is **recomputed from the live index at that moment** and sent as exact point ids, and only for documents that passed verification (orphan documents have nothing to verify first). A single request carries at most 5,000
point ids per collection, and a finding's evidence lists at most 50 ids; both are marked as truncated when capped.
6. **Verify again**, then the plan is `completed`. Every step is in the audit history.

**Plan statuses:** `draft` > `triggered` > `completed`, or > `cleanup_pending` > `cleanup_triggered` > `completed`, or `partial` / `failed`
(re-triggering sends only the failed documents). **Item statuses:** `planned`, `reindexed` (new generation verified), `awaiting_cleanup`,
`completed`, `failed`.

The webhook contract and a runnable receiver are in [docs/repair-webhook.md](docs/repair-webhook.md) and
`examples/reference_worker/worker.py`. The platform's repair callback (`POST /api/repairs/{id}/callback`) is authenticated by that same
HMAC signature, not by a login.

---

## 8. Impact and cost, blast radius, reports

- **Cost model.** Chunks to regenerate come from the manifest's expected chunk count (fallback: about 4 bytes of source per token),
  multiplied by *Tokens per chunk* and *Embedding price*. The comparison figure is the same calculation for the whole corpus, so
  "saved vs re-embedding everything" is real arithmetic on your own documents.
- **Blast radius** has three scenarios (section 4). Query impact is computed from the retrieval log you send to `POST /api/query-log`
  (only document ids and a hash of the query are kept, never the query text); without a log it says so.
- **Integrity report.** `GET /api/report?format=md|csv|json` (or the Documents buttons, or `ragi report`) lists exactly which documents
  are inconsistent, with each issue, its detail and its recommended fix.

---

## 9. HTTP API reference

Interactive docs are at `/docs`. Authentication: **public**; **session** (signed-in browser); **session or key** (a signed-in browser or
`Authorization: Bearer ragi_...`); **session only** (an API key is refused); **HMAC** (a signed worker callback).

| Method | Path | Auth | What it does |
|---|---|---|---|
| GET | `/` | public | the dashboard |
| GET | `/healthz` | public | liveness plus ledger reachability and whether setup is required |
| GET | `/api/session` | public | who you are, whether sign-up is open, whether setup is required, whether your workspace is ready |
| GET | `/api/auth` | public | legacy: whether a single-user API key is required |
| POST | `/api/auth/register` | public (5 per hour per network) | create an account and sign in |
| POST | `/api/auth/login` | public (8 per account and 30 per network per 15 min) | sign in |
| POST | `/api/auth/logout` | session | end this session |
| POST | `/api/auth/password` | session only (10 per 15 min) | change password; signs out other sessions |
| GET | `/api/settings` | session only | every group with its fields, values (never secrets), whether each is configured, and its last test |
| PUT | `/api/settings/{kind}` | session only | save one group (`s3`, `manifest`, `qdrant`, `pipeline`, `repair`, `alerts`, `policy`) |
| POST | `/api/settings/{kind}/test` | session only (30 per 10 min) | run the real connector and return the check list; with a body it tests unsaved values |
| GET | `/api/keys` | session only | list API keys |
| POST | `/api/keys` | session only | create a key (token shown once) |
| DELETE | `/api/keys/{key_id}` | session only | revoke a key |
| GET | `/api/overview` | session or key | health, counts, trend, latest runs |
| GET | `/api/connections` | session or key | connector status |
| POST | `/api/audits` | session or key | run an audit (`tenant`, `documents`, `probe`, `wait` options) |
| GET | `/api/audits` | session or key | recent runs |
| GET | `/api/audits/{run_id}` | session or key | one run |
| GET | `/api/issues` | session or key | list issues (filters `status`, `severity`, `type`, `tenant`, `q`, paging) |
| GET | `/api/issues/{issue_id}` | session or key | one issue with its timeline |
| POST | `/api/issues/{issue_id}/ignore` | session or key | ignore with a reason |
| POST | `/api/issues/{issue_id}/reopen` | session or key | reopen an ignored issue |
| GET | `/api/documents` | session or key | document states (filters and paging) |
| GET | `/api/document` | session or key | one document; `live=true` adds the three-way source/manifest/index view |
| GET | `/api/report` | session or key | the integrity report (`format=json\|md\|csv`) |
| GET | `/api/recommendations` | session or key | the reindex recommendation and cost |
| POST | `/api/blast-radius` | session or key | blast-radius analysis |
| POST | `/api/query-log` | session or key | ingest retrieval logs (up to 5,000 rows per call) |
| GET | `/api/history` | session or key | the merged audit trail |
| POST | `/api/repairs` | session or key | create a repair plan |
| GET | `/api/repairs` | session or key | list plans |
| GET | `/api/repairs/{plan_id}` | session or key | one plan with its events |
| GET | `/api/repairs/{plan_id}/payload` | session or key | preview the reindex webhook body |
| POST | `/api/repairs/{plan_id}/trigger` | session or key | send the reindex request to your worker |
| POST | `/api/repairs/{plan_id}/verify` | session or key | verify the plan's documents |
| POST | `/api/repairs/{plan_id}/approve-cleanup` | session or key | request removal of superseded vectors |
| POST | `/api/repairs/{plan_id}/callback` | HMAC | called by your worker when it has finished |
| POST | `/api/demo/reset` | n/a | demo mode only (404 elsewhere) |

Cookie-authenticated writes must come from the site itself (the `Origin` header is checked). Errors: `401` sign in, `403` not allowed,
`409` setup incomplete or an audit already running, `422` a value was rejected (the message says which field and why), `429` rate
limited, `502` your infrastructure refused or failed (the message explains), `503` the deployment is not set up, `504` the audit ran out of time.

---

## 10. Command line reference

Install with `pip install -e ".[dev]"`; the command is `ragi`.

| Command | What it does |
|---|---|
| `ragi serve [--host H] [--port P] [--demo] [--app]` | run the API and dashboard (default `127.0.0.1:8000`); `--demo` the synthetic world, `--app` the multi-user mode |
| `ragi demo [--seed N]` | seed the demo world and audit it, print a summary |
| `ragi audit [--tenant T] [--no-probe] [--json] [--fail-on SEVERITY]` | run an audit now; with `--fail-on` it exits **2** if open issues at or above that severity remain (cron/CI gating) |
| `ragi issues [--status S] [--severity S] [--type T] [--tenant T] [--limit N]` | list issues from the ledger |
| `ragi report [--format md\|json\|csv] [--all] [-o FILE \| --output FILE]` | the document-level integrity report |
| `ragi connections` | test the ledger, S3, the manifest database and Qdrant, naming whichever is misconfigured |
| `ragi init-db` | create the ledger tables (idempotent) and check connectivity |
| `ragi users list` / `ragi users delete EMAIL --yes` | list users, or delete a user and everything in their workspace (app mode; needs `RAGI_DATABASE_URL` and `RAGI_SECRET_KEY`) |
| `ragi repair plan\|trigger\|verify\|approve-cleanup [PLAN_ID] [--min-severity S] [--tenant T]` | drive the repair workflow |

---

## 11. Environment variables

**Server-level settings in `app` mode** (set in Vercel / your environment; users cannot change them):

| Variable | Default | Meaning |
|---|---|---|
| `RAGI_MODE` | `demo` | `app`, `live` or `demo`. The Vercel entrypoint defaults to `app`. |
| `RAGI_DATABASE_URL` | `sqlite:///./data/ragi.db` | where accounts and the ledger live. **Must be Postgres on serverless** (the app refuses a temporary database there). |
| `RAGI_SECRET_KEY` | none | 32+ random characters; encrypts users' stored secrets. Comma-separate `new,old` to rotate. |
| `RAGI_ALLOW_REGISTRATION` | `true` | `false` closes sign-up. |
| `RAGI_ALLOW_PRIVATE_HOSTS` | `false` | `true` lets users point connectors at private addresses (self-hosting only). It is the SSRF guard. |
| `RAGI_SESSION_DAYS` | `7` | session lifetime (sliding). |
| `RAGI_MAX_AUDIT_SECONDS` | `0` | audit time budget; `0` is unlimited, and 50 is implied on serverless. |
| `RAGI_SYNC_AUDITS` | `false` | run audits inside the request (implied on Vercel). |
| `RAGI_PROBE_RETRIEVAL`, `RAGI_PROBE_MAX`, `RAGI_PROBE_TOP_K` | `true`, `25`, `10` | retrieval-probe switches and limits. |
| `RAGI_S3_WORKERS` | `16` | parallel HEAD requests during an S3 inventory. |
| `RAGI_QDRANT_PAGE_SIZE` | `1000` | points per Qdrant scroll page. |

**Single-user (`live` / `demo`) settings** use the same names as the Settings fields (section 5.9), plus: `RAGI_API_KEY` (require a
shared key on `/api/*`), `RAGI_AUDIT_INTERVAL_MINUTES` (built-in scheduler; `0` off), `RAGI_PUBLIC_BASE_URL` (callback base for the
repair worker). The full annotated list is in `.env.example`.

Local `.env` (git-ignored) currently holds `SUPABASE_DB_PASSWORD`, `RAGI_DATABASE_URL`, `RAGI_SECRET_KEY` and `RAGI_MODE`. Values for
Vercel are set by `scripts/vercel-env.ps1` (marks both as write-only *sensitive* variables).

---

## 12. Data model: what is stored

Everything is in the private `ragi` schema (Supabase) or one SQLite file (local). **No document contents are ever stored**, only ids,
hashes, versions, counts and evidence about them. Row-level security is on for every table and `anon`/`authenticated` have no access.

| Table | Columns | Purpose |
|---|---|---|
| `workspaces` | id, name, owner_id, created_at | one per user |
| `users` | id, email, password_hash, workspace_id, created_at, last_login_at | accounts (scrypt hash only) |
| `sessions` | token_hash, user_id, workspace_id, created_at, expires_at, last_used_at, ip, user_agent | sign-ins (only a hash of the cookie token) |
| `workspace_settings` | workspace_id, kind, config, secrets, updated_at, last_test | per-group settings: `config` readable, `secrets` Fernet-encrypted |
| `api_keys` | id, workspace_id, name, token_hash, prefix, created_at, last_used_at, revoked_at | automation keys (hash only) |
| `rate_limits` | key, window_start, count | brute-force and abuse counters |
| `audit_runs` | id, workspace_id, kind, trigger, scope, status, started_at, finished_at, stats, error | each audit; a unique index allows one `running` per workspace |
| `issues` | workspace_id, id, type, severity, status, tenant_id, document_id, collection, title, detail, evidence, action, first_seen_at, last_seen_at, first_run_id, last_run_id, resolved_at, resolved_run_id, occurrences, reopened_count, ignored_reason | the issue ledger |
| `issue_events` | id, workspace_id, issue_id, run_id, ts, event, details | issue lifecycle trail |
| `documents` | workspace_id, tenant_id, document_id, status, issue_count, worst_severity, issue_types, fingerprint, source_uri, source_hash, source_version, size_bytes, expected_chunks, indexed_chunks, manifest_status, manifest_updated_at, collections, source_present, manifest_present, index_present, last_verified_at, last_run_id | the latest verified state of every document |
| `repair_plans` | id, workspace_id, status, created_at, updated_at, items, summary | repair plans |
| `repair_events` | id, workspace_id, plan_id, ts, event, details | repair trail |
| `query_log` | id, workspace_id, ts, tenant_id, query_hash, retrieved_doc_ids | retrieval logs (query text hashed, never stored) |

`workspace_id` is on every ledger table and every query is filtered by it (section 13).

---

## 13. Security model

The full threat model, with what is and is not covered, is in [docs/security.md](docs/security.md). In short:

- **Passwords**: scrypt with a per-user salt, constant-time compare; unknown emails burn the same CPU, so timing does not reveal accounts.
- **Sessions**: a random 256-bit token in an `HttpOnly`, `SameSite=Lax`, `Secure` cookie; only its SHA-256 is stored; 7-day sliding expiry; logout and password change revoke on the server.
- **CSRF**: `SameSite=Lax` plus an `Origin` check on every cookie-authenticated write.
- **Rate limits** (database-backed, so they hold across serverless instances): 8 sign-in attempts per account and 30 per network per 15 minutes; 5 sign-ups per network per hour; 10 password changes per account per 15 minutes; 30 connection tests per workspace per 10 minutes.
- **Tenant isolation**: every ledger statement carries the workspace id; the tests attack read, modify, resolve, reset and plan-hijack across workspaces, on SQLite and a real Postgres.
- **Secrets at rest**: Fernet (AES-128-CBC + HMAC-SHA256) under `RAGI_SECRET_KEY`, which exists only in the server environment. Secrets are write-only in the UI/API. Errors and ledger rows are scrubbed of `scheme://user:password@host` credentials.
- **SSRF guard**: every host a user supplies (S3 endpoint, Qdrant URL, manifest database, repair and alert webhooks) must be public. Loopback, private, link-local (including the cloud metadata address), carrier-grade NAT, IPv4-mapped IPv6, multicast and reserved ranges are refused; hostnames are resolved and every address must be public; checked when saved **and again before every connection**. URLs may not contain credentials; databases must be `postgresql://` with only `sslmode`, `connect_timeout`, `application_name` options.
- **Read-only connectors**: S3 list/head (get only in `compute` mode); manifest queries in `READ ONLY` transactions; Qdrant scroll/retrieve/query.
- **API keys** are hashed, revocable, and cannot read settings or mint keys.
- **Web hardening**: strict `Content-Security-Policy` (`script-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, no referrer, `no-store` on API responses; the dashboard renders every value as text (document ids come from S3 keys, so they are untrusted).

**Not covered:** no email verification or password reset (no mail provider), no two-factor authentication, no teams or roles, and the DNS-rebinding window between validation and connection is narrow but not zero.

---

## 14. Deployment and operations

### 14.1 Topology
```
Browser ──HTTPS──> Vercel function (api/index.py, FastAPI, Python 3.12, ~160 MB bundle)
                        │  reads RAGI_DATABASE_URL / RAGI_SECRET_KEY (sensitive env vars)
                        ├──> Supabase Postgres (schema ragi: accounts, sessions, encrypted settings, ledger)
                        └──> the USER's own S3 / manifest Postgres / Qdrant  (read-only, public hosts only)
GitHub (main) ──push──> Vercel auto-deploy;   GitHub Actions: tests (3.10 and 3.12) + image build to GHCR
```

### 14.2 Files that make it deployable
| File | Role |
|---|---|
| `api/index.py` | Vercel entrypoint; sets `RAGI_MODE=app`; never falls back to a temporary database |
| `vercel.json` | `maxDuration` 60 s and bundles `src/**`. **No rewrites** (a catch-all rewrite makes every route 404). |
| `requirements.txt` | the only install source on Vercel (FastAPI, SQLAlchemy, psycopg, httpx, boto3, qdrant-client, cryptography) |
| `.vercelignore` | hides `pyproject.toml`, tests, docs, `.env*` from the upload |
| `supabase/migrations/20261107000000_ragi_ledger.sql` | v1 ledger |
| `supabase/migrations/20261108000000_multi_user.sql` | v2 accounts and workspace-scoped ledger; **refuses to run if the old tables hold data** |
| `scripts/vercel-env.ps1` | sets the two secrets on Vercel (run by you; writes exact bytes: no BOM, no newline) |
| `Dockerfile`, `docker-compose.yml` | container image and a full local stack (MinIO, Postgres, Qdrant, seed, reference worker, app) |
| `.github/workflows/ci.yml` | tests against Postgres, Qdrant (API key enforced) and S3 over HTTP; image build and push |

### 14.3 Setup recap
1. `npx vercel login`, then `npx vercel link --project rag-integrity-platform`.
2. `supabase link --project-ref <ref>` then `supabase db push` (13 tables, RLS on).
3. Put `RAGI_DATABASE_URL` in `.env`, run `scripts/vercel-env.ps1` yourself (it generates and keeps `RAGI_SECRET_KEY`).
4. Deploy: `npx vercel deploy --prod`, or push to `main`.

### 14.4 Day-to-day
- **Roll back**: `npx vercel promote <previous-deployment-url>`.
- **Users**: `ragi users list`, `ragi users delete someone@example.com --yes`.
- **Close sign-up**: set `RAGI_ALLOW_REGISTRATION=false`.
- **Rotate the secret key**: set `RAGI_SECRET_KEY` to `new,old`, redeploy; stored secrets keep working and new saves use the new key.
- **Scheduled audits**: serverless has no scheduler. Create an API key in Settings and call `POST /api/audits` from GitHub Actions or cron.
- **Large corpora**: audit per tenant, or run `ragi audit` outside serverless.

---

## 15. Verification status

**Verified** (and how):
- **207 tests.** On a plain checkout with no external services **185 pass and 22 skip** (checked on the pushed commit). The 22 skipped need real servers; when every real service was attached, all 197 tests that existed at the time passed (before the 10 guide tests were added). Per file: accounts 22, api 15, app connectors 4, app mode 46, connectors 19, docs 10, engine 11, live mode 6, Postgres integration 5, real Qdrant 8, reference worker 3, S3 over HTTP 5, schema 4, security 26, serverless 8, service 15.
- The engine finds **exactly** the injected faults (compared with ground truth) in the in-memory demo *and* through the real connector code.
- A **real Qdrant 1.20 server** (checksum-verified official build, API key enforced): paging past one page, server-side filters, empty-vector detection, probes, wrong-key and unreachable diagnostics.
- A **real Postgres engine**: both migrations apply in order and idempotently, RLS on all 13 tables, the destructive migration refuses to drop data, workspace isolation and the one-running-audit index hold.
- **S3 over real HTTP** with a custom endpoint and path-style addressing (inventory, compute hashing, scoped listing, diagnostics).
- The app run against the **real Supabase** with a throwaway account (16 of 16 checks: empty workspace, SSRF refusal, secrets encrypted at rest, API keys, logout, login), then cleaned to zero rows.
- The **live site**: healthy, connected to Supabase, protected endpoints return 401 to anonymous visitors, headers present, sign-in and sign-up screens render in a real browser.

**Not verified:**
- A user's own S3 bucket, manifest database and Qdrant cluster on the live site (none existed to test against).
- `docker-compose.yml` was validated but never run (Docker Desktop could not start on the development machine).
- Registration and login **on the live site itself** were not exercised by automation (account creation there is yours to do); the same flows were tested locally against the real Supabase.

---

## 16. Limits and caveats

- **Scale**: aggregation is in memory, measured at about 19,000 vectors per second and about 600 bytes per vector on a laptop (about 1M vectors is roughly a minute and 600 MB). On Vercel an audit must finish in about 50 seconds.
- **S3 hashing**: `metadata` mode costs one HEAD per object. For very large buckets store a SHA-256 in object metadata at upload time.
- **One workspace per user**; no teams, roles, email verification, password reset or two-factor authentication.
- **Collections**: a document is expected in at least one configured collection; per-collection expectations are not modelled.
- **Retrieval probe** replays an affected chunk's own vector, not real user traffic: it proves searchability and rank, not user impact.
- **Integrations**: S3, PostgreSQL/Supabase and Qdrant only.
- The claim that no competitor does exactly this is a hypothesis to validate with customers; nothing in this repository proves it.

---

## 17. Lessons learned while building

Real problems found and fixed, worth knowing because they recur:

- **Vercel and FastAPI**: a catch-all `rewrites` entry makes the app see the rewritten path, so every route returns 404. Remove it; Vercel routes FastAPI itself.
- **Serverless threads**: background threads are frozen after the response. Audits run inside the request, with a time budget.
- **Windows PowerShell 5.1**: text a program writes to stderr becomes a terminating error; `a,b` is turned into a list and passed as `a b`; piping adds a line ending; and .NET writes a UTF-8 byte-order mark to redirected stdin in a UTF-8 console. An invisible `U+FEFF` at the start of a stored database URL would have broken the app. The setup script feeds exact bytes from a short-lived temp file.
- **boto3**: `max_attempts` counts *retries*, so "no retries" is `0`. Diagnostics use a fast client so an unreachable endpoint fails in seconds.
- **Qdrant client**: a URL without a port defaults to 6333 even for https; `check_compatibility=False` avoids a version-check round trip per client.
- **Docker Desktop on Windows** can crash at startup on a stale `dockerInference` socket that needs an administrator shell to remove.
- **Comparisons**: PowerShell's default string comparison ignores zero-width characters; use ordinal comparison when exactness matters.

---

## 18. Glossary

| Term | Meaning |
|---|---|
| **RAG** | retrieval-augmented generation: answers are generated from documents retrieved from a vector index |
| **Chunk** | a piece of a document that is embedded and stored as one vector |
| **Embedding / vector** | the numeric representation of a chunk used for similarity search |
| **Point** | one stored vector (plus payload) in Qdrant |
| **Payload** | the metadata attached to a point (document id, hash, chunk id, ...) |
| **Manifest** | the table where your pipeline records what it processed |
| **Fingerprint** | the parser, chunking, embedding and preprocessing configuration used to build a document's vectors |
| **Tenant** | a customer or business unit whose documents must stay separate |
| **Workspace** | one user's private area of this product: their connections, issues and history |
| **Ledger** | the database of issues, documents, runs and plans |
| **Scope** | the part of the corpus an audit covers (all, one tenant, or specific documents) |
| **Grace period** | how long a recently changed document is allowed to be "in flight" before it is judged |
| **Probe** | a search against the live index that shows whether bad content can actually be returned |
| **SSRF** | server-side request forgery: tricking a server into connecting to internal addresses |
| **RLS** | row-level security in Postgres |
| **BOM** | byte-order mark: an invisible character some tools put at the start of text |
