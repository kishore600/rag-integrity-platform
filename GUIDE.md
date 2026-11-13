# RAG Integrity: the complete guide

This is the full reference for everything that was built: what it is, how it works, every screen, every Settings field, every
issue it can raise, every API endpoint and command, the data it stores, how it is secured and deployed, and what was and was not
verified. The tables of settings, endpoints, commands, environment variables and database columns were extracted from the code,
and `tests/test_docs.py` fails if this file drifts from the code.

**Contents**
1. [What it is](#1-what-it-is)
2. [What was built](#2-what-was-built)
3. [How it thinks: the mental model](#3-how-it-thinks-the-mental-model)
4. [The interface, page by page](#4-the-interface-page-by-page)
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
| **Supabase project** | `rag-integrity` (ref `uyoewjceiiwlmmhsdlga`, region ap-northeast-2) | accounts, sessions, encrypted connection secrets, and the ledger (14 tables in the private `ragi` schema) |
| **GitHub repository** | `kishore600/rag-integrity-platform` (private) | source code, CI, and the Vercel auto-deploy trigger |
| **CI** | GitHub Actions | runs the tests on Python 3.10 and 3.12 against a real Postgres, a real Qdrant server and S3 over HTTP; builds the Docker image and publishes it to GHCR |

Your S3 bucket, manifest table and Qdrant cluster are **not** part of the product: each user connects their own.

### 2.2 The code, module by module (`src/ragintegrity/`)

| Module | Lines | What it does |
|---|---|---|
| `models.py` | 214 | the vocabulary: `SourceDoc`, `ManifestRow`, `IndexedChunk`, `Fingerprint`, `Finding`, `DocSummary`, `Scope`; enums for issue types, severities, actions |
| `ids.py` | 67 | how an ID is written: a number, a decimal and text for the same ID become one text form; the form a number takes in a filter |
| `config.py` | 216 | every `RAGI_*` setting (pydantic-settings), identifier validation |
| `connectors/s3.py` | 326 | read-only S3 inventory, hash modes, key parsing, `diagnose()` for the connection test |
| `connectors/postgres.py` | 315 | read-only manifest reader (READ ONLY transactions, column mapping), `diagnose()` |
| `connectors/qdrant.py` | 343 | read-only vector scan (scroll), retrieval probe, `diagnose()` |
| `connectors/resilience.py` | 96 | retry with backoff for requests to the index: which failures are worth retrying, rate limits, never past the time budget |
| `connectors/payload.py` | 101 | maps a Qdrant payload to the canonical chunk record (supports dotted paths) |
| `connectors/factory.py`, `base.py` | 57 | connector contracts and the demo/live factory |
| `engine/index_state.py` | 226 | classifies every vector as it is scanned (fresh / stale / outdated / unknown / orphan) |
| `engine/reconcile.py` | 715 | the reconciliation engine: compares source vs manifest vs index and emits findings |
| `engine/retrieval.py` | 58 | retrieval probes: can the bad content actually be returned by a search? |
| `engine/versions.py` | 156 | the expected-versus-actual table for one document (source version and hash, chunk counts, chunk ids, chunk hashes, pipeline settings) and its verdict |
| `engine/deletions.py` | 172 | deletion and retrieval verification: deleted documents, their remaining vectors, a search test, the verdict and the advice |
| `engine/audit.py` | 485 | pulls the three inventories, enforces the time budget, runs the engine |
| `engine/coverage.py` | 665 | duplicate-ID warnings, and the setup and coverage check (what the three systems call their documents, and whether the IDs line up) |
| `engine/planning.py` | 100 | turns issues into per-document repair items and estimates the work and cost |
| `engine/blast.py` | 117 | blast-radius analysis |
| `engine/isolation.py` | 156 | the tenant isolation summary, per-tenant status, five checks and the evidence report |
| `engine/drills.py` | 60 | the read-only isolation drill (pretend leak on one real document) |
| `ledger.py` | 923 | the workspace-scoped store of issues, documents, runs, plans, and the account tables (SQLite locally, Postgres/Supabase in production) |
| `service.py` | 568 | the one object the API/CLI use: audits, locking, overview, inspection, friendly errors |
| `repair.py` | 215 | plan, signed webhook, independent verification, approved cleanup |
| `alerts.py`, `report.py` | 115 | Slack-compatible alerts; markdown/CSV/JSON integrity report |
| `notifications.py` | 269 | what to tell people when an audit finishes: the notification and the email, each with its next-step buttons (3.14) |
| `mailer.py` | 93 | email over SMTP: bounded, one message per recipient, never raises (3.14) |
| `security.py` | 180 | password hashing, the secret vault, SSRF guard, credential scrubbing |
| `accounts.py` | 242 | users, sessions, rate limits, API keys, encrypted per-workspace settings |
| `workspaces.py` | 425 | the declarative Settings specification, validation, per-workspace service, connection tests |
| `api/app.py` | 746 | the HTTP API and authentication |
| `api/static/` | built | the committed build of the web interface (`index.html` and hashed files in `assets/`): deploys need no Node step |
| `frontend/` (outside `src/`) | 10,326 | the web interface source: React, TypeScript, Vite, Tailwind, TanStack Query and Table, Recharts; `npm run build` writes `api/static/` |
| `cli.py` | 292 | the `ragi` command |
| `demo/` | 501 | a synthetic world with 47 injected faults, a toy pipeline, seeding for real infrastructure (local exploration and tests only) |

Also: `api/index.py` (the Vercel entrypoint), `examples/reference_worker/worker.py` (a runnable receiver for the repair webhook),
`supabase/migrations/` (4 migrations, 392 lines of SQL), `scripts/vercel-env.ps1` and `scripts/seed_live.py`, `Dockerfile`,
`docker-compose.yml`, `.github/workflows/ci.yml`, and `docs/`.

**Size:** about 10,200 lines of Python in `src`, 7,500 lines of tests, 10,326 lines of interface TypeScript and CSS, 392 lines of SQL.

### 2.3 The three ways it can run

| Mode (`RAGI_MODE`) | Who it is for | Accounts | Connections come from |
|---|---|---|---|
| `app` | **the hosted product**, or self-hosting it for several users | sign-up / login | each user's own *Data Sources* (encrypted in the database) |
| `live` | one team, one set of infrastructure | none (optional `RAGI_API_KEY`) | environment variables |
| `demo` | exploring locally | none | a built-in synthetic corpus with injected faults |

The live site runs `app` mode. Demo mode never runs on it.

---

## 3. How it thinks: the mental model

### 3.1 Three inventories, one key
Documents are identified by `(tenant_id, document_id)`. For each key the engine looks at what the **source** says, what the
**manifest** says, and what the **index** holds, and decides whether they agree.

**A number and its text are the same ID.** IDs are compared as text, and a whole number is always written without a decimal part:
`2329961` (a number in a database column or in a Qdrant payload), `2329961.0` or `2329961.00` (a decimal, from a `numeric` column or a
JSON library) and `"2329961"` (text, as in a file name) are one ID. This applies to document, tenant and chunk IDs read from the manifest and
from payloads. Filters follow the same rule: a scoped read of Qdrant matches both the text and the number form of an ID (if a server refuses
the number form, the text form is used alone), and a scoped read of the manifest compares in the form the column stores (numbers against a number
column, where an ID that is not a number cannot be present; the text form against a text column; any other type as text). Two limits: Qdrant
cannot filter by a decimal such as `2329961.0` (store IDs as text or whole numbers, or turn off **Only audit documents found in the source (S3)**),
and only the *type* is reconciled. IDs that differ in letter case, spaces, leading zeros, a prefix or a file extension are different IDs: the
setup check (3.10) shows such pairs and says so, and does not guess.

**A hash is the same hash however it is spelled.** Content hashes are compared by value: upper or lower case, quotes, spaces and an algorithm
prefix (`sha256:`, `sha-256=`, `md5:`) are ignored, for the source hash in a payload, in the manifest and in S3, and for chunk hashes. Before this,
a payload that stored `sha256:<hex>` made every document look stale against a file whose hash is bare hex.

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

**Health score** = (healthy + pending documents) ÷ all documents, shown as a percentage. Green at 90% and above, amber at 70% and
above, red below.

### 3.4 What an audit does, step by step
1. Take a lock: **one audit at a time per workspace**, enforced by a database index (so it holds across serverless instances). A run
   that crashed and is still "running" after the audit time budget plus 90 seconds (6 minutes on the hosted service; 15 minutes only
   where there is no time budget), for example a serverless function that was killed before it could record a result, is marked failed
   ("abandoned") automatically the next time the app checks, so it cannot keep **Run audit** disabled.
2. Read the **source inventory** from S3 (keys, sizes, modified times, content hashes).
3. Read the **manifest rows** (and the chunk manifest if configured). While reading, count document IDs that appear twice (two files in S3
   or two rows in the manifest) and rows whose ID is empty: see **Warnings about IDs** below.
4. **Scan the vector index** page by page, classifying every point as above. Memory stays proportional to the corpus, not to scan buffers.
   When only the source's documents are audited (**Only audit documents found in the source (S3)**) the scan is made in slices of documents, and
   steps 5 to 7 are done for each slice as soon as it is read (3.12). Requests that fail for a reason that can pass are retried with backoff.
5. **Reconcile**: run the per-document checks and emit findings.
6. **Retrieval probes** (up to 25 per audit): for findings about content that should not be searchable, query the live index with one
   affected chunk's own vector, filtered to the owning tenant, and record the rank. A confirmed probe escalates severity.
7. **Apply to the ledger**: new problems become issues, previously known ones are updated, ones no longer seen are resolved, regressions
   are reopened. Per-document state is refreshed.
8. **Alert** (if configured) about *new, reopened or escalated* issues at or above the minimum severity.
9. Record the run with its statistics and duration.

**Time budget on Vercel:** an audit that has not finished within 270 seconds (the function limit is 300) stops with a clear message
that says which step was running, instead of being killed. The budget is checked while listing S3 and between Qdrant pages, not only
between documents. Each step is also written to the run record, so a run that is ever cut off still shows where it stopped. Audit one
tenant at a time, or run `ragi audit` elsewhere.

**Warnings about IDs.** If two S3 files get the same document ID (for example a key pattern that captures only the file name when the
same name exists in two folders), or two manifest rows share an ID, the audit can follow only one of them, and before this check the other
disappeared without a word. The audit still follows one item per ID, so its findings are unchanged, but the run now lists what it saw in
`stats.warnings` (an empty list when all is well). Each warning has a `code` (`duplicate_source_ids`, `duplicate_manifest_ids`,
`empty_manifest_ids`), `severity` (`warning`), a `title`, a plain-language `detail`, a `fix`, a `count` and up to five `examples` that name the ID
and where its copies are (up to 200 duplicated IDs are remembered with their locations; all are counted). With **Only audit documents found in
the source (S3)** on, duplicates among manifest rows for documents that are not in S3 are ignored, as those rows are. A manifest row with no ID is
skipped (it used to be recorded as a document called `None`). The warnings are part of the run, so they are returned by `GET /api/audits/{run_id}`
and in `latest_full_run.stats` of the overview.

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
complete, done, ready, ok, processed, true` (so a true/false column such as `is_indexed` can be mapped as the status); **in flight** - `pending, queued, processing, running, in_progress, indexing, parsing,
embedding`; **failed** - `failed, error, errored, failure`; **deleted** - `deleted, tombstoned, removed`.

### 3.9 Tenant isolation
A **tenant** is one customer (or group) whose documents must stay private from the others; its label travels with every vector as
`tenant_id`. Isolation fails when one tenant's content can be returned to another. Every **full** audit now builds an isolation picture
from what it already read and stores it with the run (`stats.isolation`); scoped audits do not replace it.

**Result.** Overall: `clean`, `attention`, `leak`, `not_applicable` (only one tenant exists, so there is nothing to keep apart) or
`limited` (see below). Per tenant: `clean`, `attention`, `leak` or `single_tenant`, worst first.
- `leak`: documents that belong to another tenant are indexed under this one (the existing **Tenant mismatch** finding, critical).
  When the retrieval probe is on, leaks are also searched live as the wrong tenant (up to the audit's limit of 25 searches), and the
  picture says how many were searched and how many were **confirmed reachable**.
- `attention`: some vectors have no tenant label, or (when permissions are recorded) no permission hash, or a document's vectors carry
  a permission hash that differs from the manifest (the existing `acl_mismatch` problem, high).

The overall sentence is wording, not data: it is produced when the result is read, so a wording change also applies to audits stored earlier.

**Five checks** are listed: documents under the wrong tenant; leaks confirmed reachable by a real search; every vector carries a tenant
label; permission labels agree with the manifest; every vector carries a permission label. Each is `pass`, `warn`, `fail` or `na`.
"Permissions are recorded" means any vector or manifest row has a permission hash; if none does, those two checks are `na`.
A check that was not run is `na` and its detail starts with "Not checked: ..." and gives the reason; it never reads like a pass.

The "leaks confirmed reachable" check is `fail` when a live search returned a leaked document as the wrong tenant; `warn` when no leak was
searched (searches are off, or the audit's limit on searches was reached) or only some were; `pass` only when every leak was searched and
none was returned (the labels are still wrong, and the first check still fails); `na` when there are no leaks. The summary also reports
`leaks_tested_by_search` and `leaks_confirmed_reachable`.

**Findings are live.** The overall status, cards and checks describe the last full audit. The open findings listed with them are read from
the issue list as it is now, so a scoped re-audit, an ignore or a repair can make them differ. The response says so:
`findings_live: true`, and `findings_changed_since_audit: true` when the open counts no longer match the audit's.

**Limit.** The check needs the whole index. With **Only audit documents found in the source (S3)** on, vectors under another tenant are
never read, so the result is `limited` and says so instead of claiming `clean`. Reading the whole index can run past the hosted time
limit on a large one (the audit then fails with a clear message, as it does after about 700,000 vectors on the 270-second budget), so
for a large index run `ragi audit` from your own computer and turn the switch off on the hosted site only when the index is small. The
evidence report explains a 0.0% tenant-label figure: the payload has no tenant field, so every vector counts as the default tenant.

**Isolation drill.** A read-only demonstration on one of your own documents: the app reads it exactly as an audit does, then pretends in
memory that all its vectors carry a different tenant and runs the normal checks. It shows the finding the audit would raise (critical
**Tenant mismatch**) and the alert text it would send, built by the same function a real audit uses, so it is the real wording. It writes
nothing to S3, the database or the index, saves no issue and sends no alert. With no document given, a healthy indexed one is chosen.

**Evidence report.** `GET /api/isolation/report?format=md` is a plain page for a customer's own customers or auditors: result,
checks, tenants and open findings, stating that it was produced read-only.

### 3.10 Setup and coverage check
An audit is only as good as the ID it matches on. If a file is called `2329961.pdf` and the manifest says `bill-2329961`, every document looks
missing and the audit is noise. The setup check answers one question before you trust an audit: **do S3, the manifest and Qdrant call the same
documents by the same ID, and do the numbers add up?** Run it with `POST /api/setup-check` or `ragi setup-check` (exit code 1 when the result is
`not_ready`). It is not an audit: it stores nothing (no run, no issue, no alert), does not take the audit lock and writes to nothing.

**What it reads, and how little.** S3: object *names* only (a listing: no HEAD, no download, no hashing), at most 200,000 files. The manifest: its
rows, at most 500,000. Qdrant: the document and tenant IDs of a random sample of 1,000 points (the first points of each collection on a server that
cannot sample; the result says so), the approximate size of the collection, and a lookup of 200 of your S3 documents by ID (reading at most 50,000
points and giving up after 40 seconds, which is reported as a warning, not a failure). The whole look has its own budget of 120 seconds (less on a
host with a shorter time limit). Anything cut short is listed under `limits`. With **Look up files from the manifest** on, the bucket is not
listed: the check heads (HEAD request only) up to 200 of the files the manifest names instead. A system that cannot be read is a failed check
with the reason; the other systems are still read. If a connection is not set up at all the answer is a `not_ready` result with a `connections`
check, not an error.

**The checks.** Each has an `id`, a `name`, a `status` (`pass`, `warn`, `fail` or `na`), a `detail` in plain words and, when something is wrong,
a `fix`, `examples` and sometimes a `hint`.

| Check (`id`) | What it asks | Fails when |
|---|---|---|
| Files in S3 (`source_files`) | do the file names give document IDs? | the bucket cannot be read, there are no files, or no file name matches the key pattern (examples are shown); warns when more than half of the files do not match (skipping some is normal when the pattern is meant to select only some files, and the result only says so) |
| One file per document ID (`source_ids_unique`) | does each ID belong to one file? | 5% or more of the IDs are shared by several files (warns below that) |
| Rows in the manifest (`manifest_rows`) | can the manifest be read, and do the rows have IDs? | it cannot be read, has no rows, or no row has an ID; warns when some rows have no ID |
| One manifest row per document ID (`manifest_ids_unique`) | does each ID have one row? | 5% or more of the IDs have several rows (warns below that) |
| S3 against the manifest (`source_vs_manifest`) | what share of S3 documents has a manifest row with the same ID? | fewer than 20% (warns from 20% to 80%); shows IDs found on one side only and, if they look like the same document, how they differ |
| Manifest against S3 (`manifest_vs_source`) | what share of manifest rows has a file? | never fails; warns, and recommends **Only audit documents found in the source (S3)**, when many rows have no file |
| Files the manifest names (`manifest_files_exist`) | lookup mode only: do a sample of the manifest's files exist in S3? | fewer than 20% exist, or no manifest row names a file of this bucket |
| Files without a manifest row (`lookup_blind_spot`) | lookup mode only: a reminder that a file with no manifest row is not seen | it is always a warning while that setting is on |
| Tenant names agree (`tenant_labels`) | do the sides use the same tenant names? | two sides share no tenant name at all (their documents cannot match; the hint says when the same IDs exist under another tenant name) |
| Document IDs in Qdrant (`index_ids`) | do the points carry a document ID, and how is it stored (numbers, text, decimals)? | Qdrant cannot be read, the collection is empty, or no sampled point carries the mapped payload field; warns for missing IDs on some points, decimals, or numbers mixed with text |
| S3 against Qdrant (`source_vs_index`) | of 200 S3 documents, how many have pieces in Qdrant under the same ID? | fewer than 20% (warns from 20% to 80%) |
| Qdrant against S3 (`index_vs_source`) | what share of the sampled points belongs to a document S3 or the manifest knows? | never fails; warns when most of the index belongs to other documents, unless **Only audit documents found in the source (S3)** is on (then those points are ignored and it passes) |

"Pass" starts at 80% because the gaps inside a pass are real documents that an audit reports one by one: this check is about whether IDs can
be matched at all, not about how well your pipeline is doing. **Overall** `status`: `not_ready` if any check fails, `needs_attention` if any
warns, else `ready`; `headline` says which in a sentence, and `next_steps` lists every `fix`.

**What else is in the result.** `coverage` (`source_to_manifest`, `manifest_to_source`, `source_to_index`, each `matched`, `of`, `percent`, or
`null` when it could not be measured), `counts` (files, documents, rows, approximate points, points sampled), `ids_at_a_glance` (five IDs from each
side, to compare by eye), `id_types_in_index` (how many sampled IDs are stored as `integer`, `digits`, `text`, `decimal` or `other`), `limits`,
`generated_at` and `duration_seconds`.

**It never guesses.** When the unmatched IDs on two sides differ only by letter case, spaces or leading zeros, or one contains the other (a prefix
or suffix), the check says so with examples. RAGGuard still compares IDs exactly: an ID clean-up rule is not available yet, so make both sides
write the ID the same way or change the key pattern. The call needs a session or an API key; in the hosted app it is limited to 20 checks per
workspace per 10 minutes because it opens connections to your systems.

### 3.11 Document version integrity
An index can be wrong while the pipeline says "success" and the chunk count is right: a document was updated to version 3, the pipeline ran,
and every chunk in the index still describes version 2. A chunk id alone cannot see that, because the same ids are reused. The audit compares the
**revision** of what the index holds with the source, and `GET /api/document?live=true` returns the evidence for one document as a table
(`live.version_check`) with a verdict:

| Property | Expected | Actual |
|---|---|---|
| Source version | `v3` (the source) | `v2` (what the payloads say, or the manifest's `indexed_version` as a fallback) |
| Source hash | the file's hash | the hash(es) the vectors carry, with counts when they differ |
| Chunk count (any revision) | the chunk table's count, else `expected_chunk_count` | the distinct chunk ids present, of any revision |
| Chunks of the current revision | the same count | how many belong to the current revision (the trap: the line above can match while this is 0) |
| Chunk IDs | the ids in the chunk table | how many of them are found in the current revision, how many are missing, how many are not in the current version at all |
| Chunk hashes | as recorded by the pipeline | how many chunks carry the hash the chunk table records |
| Parser version, Chunking version, Chunk size, Chunk overlap, Embedding model, Embedding model version, Embedding dim, Preprocessing | your target pipeline | what the vectors were built with (a row only when it can be compared or varies inside the document) |

Each row has a `status` (`match`, `mismatch`, `partial` or `unknown`). The verdict is one of `in_sync`, `version_mismatch` ("24 chunk(s) exist in the index
(24 expected), but they belong to an outdated revision of the document"), `partly_outdated`, `config_changed`, `unknown_revision` (the payloads carry no hash
or version, so the revision cannot be verified; counts and ids are still compared), `not_indexed` and `source_missing`. `points_by_revision` counts the
vectors by `current`, `older_revision`, `older_config` and `revision_unknown`.

**How each situation is reported:**

| Situation | Found by | Reported as |
|---|---|---|
| Every chunk is from an older revision (the counts look right) | the payload's source hash or version differs from the source | `stale_embedding` (high; the evidence lists the old and the current revision) |
| The new revision is indexed and old chunks are still active, often under the same chunk ids | stale or older-configuration points next to current ones | `superseded_active`, with exactly the old point ids to remove |
| The document got shorter and its old tail was never removed | chunk ids not in the chunk table, or a chunk index at or beyond `expected_chunk_count`, among live vectors | `superseded_active` "Chunks the current version no longer has are still active" (folded into the same issue when old-revision vectors exist too); the manifest's chunk-count difference is then not reported separately |
| The payloads carry no revision, but a chunk's hash differs from the chunk table | chunk hash against the chunk table | the chunk counts as stale: `stale_embedding` with `stale_by: chunk_hash` |
| The document hash says current, but chunk hashes differ | the same comparison | `metadata_inconsistent`, problem `chunk_hash_mismatch` (medium): the chunking may have changed, or the two sides compute chunk hashes differently |
| The hash is spelled differently on two sides | hashes are compared by value | nothing (3.1) |
| The chunking or embedding settings changed | the vectors' settings against your target pipeline | `pipeline_drift` (high when the embedding model or dimension differs); one document built with mixed settings is reported without any target; half way through a re-chunking the old chunks are `superseded_active` |
| The document was modified a few minutes ago | the grace period (3.6) | `pending`, not stale |

**Changed chunking configuration.** Old vectors are `outdated` (built the old way) rather than `stale` (older content): the text is current but
the chunks differ. They are never mistaken for the new generation. While a re-chunking is under way both generations are active, which is
`superseded_active` (medium; high when a retrieval test returns old content); once only old vectors remain it is `pipeline_drift`. The target is your
**Target pipeline** settings; without one, a document whose own chunks disagree is still reported.

### 3.12 Reading a large index reliably
An audit of millions of vectors makes thousands of requests. One timeout, rate limit or dropped connection must not abort it, and an audit that could
not finish must never make documents look missing.

**Run states.** `running` (in progress; the run record shows the step, points scanned and the checkpoint), `completed` (everything was read),
`partial` (the scan stopped after finishing some slices: what was finished is reported and final, the rest is **not** reported, and the run says so) and
`failed` (nothing usable). Every result carries `stats.scan`: `status`, `complete`, `provisional`, `mode` (`sliced` or `single_pass`), `points_scanned`,
`estimated_total` (the index's own approximate size), `percent`, `pages`, `slices_done`, `slices_total`, `documents_done`, `documents_total`, `checkpoint`,
`checkpoints_saved`, `retries`, `recovered_errors`, `unrecoverable_errors`, `rate_limited`, `waited_seconds`, `resumed_from` and `stopped_because`. A scan that
stops before finishing one slice (or that is not sliced) fails and reports nothing, instead of reporting documents as missing.

**Retry with backoff.** A request is repeated when its failure can pass: a timeout, a dropped connection, or HTTP `408`, `425`, `429`, `500`, `502`,
`503`, `504`. It is tried up to 4 times, waiting 0.5 s, 1 s, 2 s (doubling, at most 10 s, each wait between 50% and 100% of that step), or as long as the
server asks in a `Retry-After` header (at most 60 s). It never waits past the audit's time budget. A refusal (`400`, `401`, `403`, `404`: a wrong key, a missing index,
no such collection) is not retried: asking again changes nothing. The counters above say how many requests were retried, how many recovered and how many gave up.

**Slices, checkpoints and resume.** With **Only audit documents found in the source (S3)** on, the index is read for a slice of documents at a time
(`RAGI_AUDIT_SLICE_DOCUMENTS`, default 5000). Each finished slice is reconciled and recorded in the ledger immediately: that is the checkpoint. If the scan
then stops (a timeout, a cluster that stays unreachable) the run ends `partial` and the Audit History shows how far it got. A **resumed** audit continues
after the last checkpoint and carries the earlier counts over, so its health score and totals are those of the whole audit:
`POST /api/audits {"resume": true}` or `ragi audit --resume`; `GET /api/overview` has `resumable_audit` (`run_id`, `documents_done`, `documents_total`,
`percent`, `stopped_because`) while one exists. If the process is killed (a serverless function at its time limit) the abandoned run is turned into a partial run
from its last checkpoint, so nothing is lost. A resumed audit that cannot reach the index again stays partial with the same checkpoint. A completed audit
after a partial one makes it history. When an audit completes, documents the ledger still holds that exist nowhere any more (not in the source, the manifest
or the index) are closed and removed, as a full audit always did; when it resumed, only documents after the checkpoint are swept.

**What does not resume.** A scan of the whole index (the setting is off) is one pass: it cannot be resumed and, if it stops, reports nothing. The isolation
picture is built from a complete audit and is left to the next full audit after a resumed one. Documents added to the source before the checkpoint are picked
up by the next full audit.

**Measured** on a local Qdrant (150,000 points, no network; `python scripts/benchmark_scan.py --synthetic 150000` repeats it, and `--collection NAME` measures a
real cluster read-only): a plain scroll reads about 9,600 points/s at page size 100, 16,700 at 256 and 45,000 at 1,000 (the default); a scroll filtered by
document id on a field without a payload index costs about one pass over the collection (0.2 s for 10 ids, 1.0 s for 5,000 points), whatever the number of ids.
That is why a slice is thousands of documents, and why the real throughput of a remote cluster (about 2,500 points/s was measured to one) is set by
latency, not by the audit.

### 3.13 Deletion and retrieval verification
A confidential document is deleted from S3. Its vectors stay in Qdrant, and a search still returns its text. `POST /api/deletion-check` and
`ragi verify-deletions` check each deleted document and answer with evidence:

| Check | Result |
|---|---|
| Source document | `Deleted` (or `Still in the source`) |
| Manifest status | the status, or `no manifest row`; anything but deleted is a mismatch (the pipeline still believes the document is indexed) |
| Vector chunks found | how many vectors remain, in which collections |
| Retrieval test | up to 3 of the document's chunks are used as queries (their own stored vectors, top 10, filtered to the tenant when the points carry one); how many of the document's chunks come back and at which rank, or `not returned` |

Verdicts: `verified_deleted` (gone from the source, the manifest and the index), `deletion_mismatch` (vectors remain; **critical** when a search returns
them, otherwise high), `manifest_not_updated` (the vectors are gone but the manifest still lists the document) and `not_deleted` (the document is still in the
source). The row gives the **recommended action**; removal itself is the repair workflow's `cleanup_vectors` plan, which waits for your approval.

**Which documents are checked:** documents an earlier audit saw in the source that are gone now, documents the manifest marks deleted, documents with an
open `orphan_vector` or `tenant_mismatch` issue (so a cleanup is verified and its issue closed), and any `documents` you name (`tenant_id`, `document_id`).
At most 200 per check (`truncated` says how many were left out). With `record` (the default) the findings are written to the issue list as a scoped run with
trigger `deletion-check`, which also resolves issues whose vectors are gone; `record: false` only looks. It is refused while an audit runs, and limited to 20
checks per workspace per 10 minutes in the hosted app. Without any earlier audit and without a deleted status in the manifest there is nothing to
verify, and the result says so.

**Audits do this too.** With **Only audit documents found in the source (S3)** on, an audit ignores other documents on purpose, but it still looks in the
index for the documents that were deleted: the ones an earlier audit saw in the source that are gone now, and the ones the manifest marks deleted.
`stats.deletion_check` counts them (`documents_checked`, `with_remaining_vectors`, `verified_gone`). Other manifest rows with no file in this source
(another document type) stay ignored. The retrieval probe filters by tenant only when the points carry one: a payload without a tenant field is searched
as a whole (before, such an index answered every probe with no hits, which read as "not searchable").

---

### 3.14 Audit notifications: in the app and by email

After every audit that finishes, RAGGuard tells you what happened and what to do next, in two places made from the same text: a **notification**
under the bell (and on the **Notifications** page, `/notifications`), and an **email**. Each carries the next step as buttons.

| How the audit ended | Notification kind | Title | Buttons |
|---|---|---|---|
| Completed, no issues | `audit_completed` | Audit complete: no integrity issues | See the run |
| Completed with issues | `audit_completed` | Audit complete: 2 critical, 3 high issues | Review critical issues (or Review high issues, or Review the issues) · Verify deletions (only when orphan vectors or wrong-tenant vectors were found) · See the run |
| Stopped part-way | `audit_partial` | Audit stopped part-way: 4,000 of 12,000 documents checked | Resume audit · Review the issues found so far (only if it found critical or high ones) · See the run |
| Failed | `audit_failed` | Audit failed | Run it again · Check connections · See the run |

The first audit of the demo, and the verification steps inside a repair, do not notify: their result is shown where they were started.

**Buttons.** An action is either a *link* (it opens a page of the app) or a *post* (it does something). There are exactly two things a button can
do, through the same signed-in session and the same endpoints as the page's own buttons: `/api/audits` (Resume audit and Run it again) and
`/api/deletion-check` (Verify deletions, which runs the check in 3.13 and says what it found). Nothing else can be a button: a notification can never
do anything its reader could not do themselves. **Resume audit** is only offered while that audit is still the one that can be resumed. After a button
that does something is pressed, the notification shows it as *done* and is marked read.

**The email.** The recipients are the sign-in addresses of the workspace's own users (in single-user modes: `RAGI_ALERT_EMAIL_TO`); in app mode nobody
else can ever be a recipient, and the operator's own address is never used. One message goes to each recipient, as text and HTML, marked
`Auto-Submitted`. **When** is the *Email me* setting: `always` (after every audit; the default), `attention` (only when an audit fails or stops part-way,
or finds a new, reopened or escalated issue at or above the minimum severity, the same rule as the Slack webhook) or `never`. The notification in the
app is created in every case.

- **The mail account** belongs to the operator: one SMTP account (`RAGI_SMTP_HOST`, `RAGI_SMTP_PORT`, `RAGI_SMTP_USER`, `RAGI_SMTP_PASSWORD`,
  `RAGI_SMTP_FROM`, `RAGI_SMTP_SECURITY` = `starttls`, `ssl` or `none`) sends every workspace's alerts. A workspace chooses only whether it gets them; it
  never supplies a mail server, a sender or an address. Without `RAGI_SMTP_HOST` and `RAGI_SMTP_FROM` no email is sent and the run says so.
- **Links in the email** are built only from `RAGI_APP_URL` (on Vercel, the production address Vercel provides), never from a request's `Host` header,
  because a link built from a request could be pointed anywhere. Without an address the email has no links and says to open RAGGuard.
- **An email link never changes anything.** Mail scanners open links, so a button that does something (Resume audit, Verify deletions, Run it again)
  links to the Notifications page, where its button is. Links that only open a page go straight there.
- **Limits.** At most 12 emails an hour per workspace; if the limit cannot be checked, no email is sent (it fails closed). A mail server is waited for
  at most 8 seconds. A failure to send never fails the audit: the run's `stats.notifications` records what happened, for example
  `{"in_app": "<id>", "email": {"sent": 1, "to": 1}}` or `{"email": {"sent": 0, "reason": "..."}}`.
- **Escaping.** Everything that came from your data (issue titles, tenant and document ids, error text) is escaped before it reaches the HTML of an email,
  and passwords in error text are removed first.

**What is stored.** The `notifications` table (12): the title, a short body, a few lines of detail (counts, and the top new issues as severity, title and
ids), the buttons, and when it was read, emailed and acted on. No document contents. Only the newest 200 per workspace are kept.

API: `GET /api/notifications` (`limit`, `unread`), `POST /api/notifications/read-all`, `POST /api/notifications/{notification_id}/read` and
`POST /api/notifications/{notification_id}/done` (the button was pressed; body `{"action": "<id of one of its buttons>"}`).

---

## 4. The interface, page by page

The web interface is a React and TypeScript app (source in `frontend/`, built into `src/ragintegrity/api/static/`). It shows only real
data from the API: nothing is sample data, and anything the product does not do yet is shown as a card marked **Not available yet**.

**The frame around every page.**
- **Left menu** (dark, 250 px; a slide-out drawer on a phone), ten pages: *Overview, Data Sources, Reconciliation, Integrity Issues* (with the
  number of open issues), *Isolation, Documents, Audit History, Integrations, Alerts, Settings*. Below them, set apart by a line, **Help and user
  guide** opens the video and the user guide (`/help`, see below); it is a link to help, not an eleventh page. At the bottom a card says **LIVE**
  (your own systems) or **DEMO** (synthetic data), the workspace name and the version.
- **Top bar**: a search box (type, then choose *Documents* or *Integrity issues*; press `/` anywhere to focus it), **Run audit**, a bell
  (open issues by severity and when the last audit ran), and your account menu (email, workspace, Settings, **Help and user guide**,
  **Sign out**).
- **Run audit** is disabled, with the reason in a tooltip, until all three connections exist, and while an audit is already running. When
  a background audit finishes you get a notice on whatever page you are on.
- On the demo server a banner on every page says the data is synthetic.
- Every list can be searched, filtered, sorted (click a column header) and paged; filters are kept in the address, so a view can be
  shared or refreshed. Every page has a loading state, an empty state that says what to do next, and an error state with **Try again**.

### The landing page, sign-in and Create account
Before you sign in, `/` is a public **landing page**: what the product does, the six ways a RAG index fails silently, how it works in three
steps, the issue types it finds, **13 real scenarios** (grouped as *Missing from search*, *Out of date*, *Left behind*, *Records disagree*
and *Wrong customer*; each says what goes wrong, what users notice, what RAGGuard shows and how it gets fixed; they are the same 13 faults
the practice lab plants, and a test keeps the two lists equal), **six moments to use it** (after every ingestion run, before changing the
embedding model, when content is deleted, when you serve several customers, when a user says an answer is wrong, when someone asks for
proof), what you get, how it is secured, which tools it works with, and a short FAQ. It states nothing that is not true of the product (no
customer logos or statistics) and has **Sign in** and **Get started** buttons and a **User guide** link. Sign-in
lives at `/login` and sign-up at `/signup`; any other address you open while signed out asks you to sign in and then lands where you were
going (except `/help`, which is public, see below). Once signed in, those two addresses lead straight to the app. The brand mark is a
faceted shield holding a check drawn as a three-node path (source, manifest and index agreeing); its source is
`frontend/src/components/brand/logo.tsx`, with copies in `public/favicon.svg` and `docs/assets/logo.svg`.

### Help and user guide
`/help` shows the narrated walkthrough video and the whole user guide inside the product. It is **public**: a visitor who is not signed in
sees it with a slim header (**Sign in**, **Get started**), and a signed-in user sees it inside the normal frame. Signed-in users reach it
from **Help and user guide** at the bottom of the left menu (highlighted while you are on any Help page) and in the account menu; visitors
from **User guide** on the landing page.
- **`/help`**: the video player (a button for each part of the video, with its time; captions from the player's captions control; the
  poster is the title card), then every chapter as a card, grouped as in `docs/user-guide/README.md` (*Set up*, *The pages*, *Putting it to
  work*).
- **`/help/<chapter>`** (for example `/help/20-isolation`, and `/help/20-isolation#the-limited-state` for a heading): one chapter. On a
  desktop a chapter list stays beside the text; on a phone it becomes a *Chapter* drop-down. Previous and next chapter links end the page.
  Tables scroll sideways when they are wide, code samples have a **Copy** button, screenshots open full size, and links between chapters
  and to headings work. A link to a file that is not part of the guide (this file, the repository README) is shown as plain text with a
  tooltip. An address that is not a chapter shows "That chapter doesn't exist".
- **One source.** The chapters are the Markdown files in `docs/user-guide`; the build reads them (and the screenshots), so the written
  guide and the Help pages cannot differ. The contents come from the tables in `docs/user-guide/README.md`.
  `tests/test_help_pages.py` fails when a chapter is missing from that README, when a link or heading anchor in the guide would not
  work in the app, when a screenshot has a size the page does not expect, or when the video buttons differ from the table in chapter 19.
- **The video** lives in `docs/user-guide/video` (the video, its WebVTT captions and the poster). `npm run build` first copies those
  files to `public/help-media/` (`frontend/scripts/sync-help-media.mjs`) and Vite copies that folder into the built files. Vercel serves
  a root `public/` folder from its CDN, which is how an 8 MB file can be served there (the serverless function cannot return more than
  4.5 MB); Docker and self-hosted servers serve the same file from `/static/help-media/`. The player tries the CDN address
  `/help-media/...` first and falls back to `/static/help-media/...`; on a server without the CDN the first request is a plain 404 and the
  console shows it once. To replace the video, change the files in `docs/user-guide/video`, update the timestamps in
  `frontend/src/pages/help/video.tsx` and chapter 19, run `npm run build` and commit `public/help-media`, the build and the docs.

The sign-in form is one screen with two modes. Email plus password; the password must be at least 10 characters, not a common password, not one
repeated character, and must not contain your email name. Errors never reveal whether an email is registered (except that sign-up
says an email is taken). Closed sign-up shows "New sign-ups are closed on this server." If the server is missing required
configuration, a "This server isn't fully set up yet" screen lists what the operator must fix.

### Overview
The answer to "is my index consistent with the source?"
- Until the three connections exist it shows **Connect your data**: three steps (source, manifest, index), each with *To do* or *Done*
  and a **Set up** button.
- **Four cards**: *Health score* (the share of documents that match the latest source exactly), *Documents* (and how many tenants),
  *Open issues* (and how many are critical or high; click to open the list), *Last audit* (how long ago, and how long it took).
- **ID warnings notice**: an amber notice under the four cards, only when the latest full audit recorded `stats.warnings` (section 3.4):
  *Some document IDs were ambiguous in the latest full audit*, one line per warning with its count, and two links, **See the details** (that
  audit's page) and **Run the setup check** (the Setup check card, `/data-sources#setup-check`). Amber, not red: the audit's findings are valid.
- **Health over time**: the score after each full audit (it needs two audits before it can draw a line).
- **Open issues by severity** (a donut with counts and shares) and **Issues by type** (each bar opens the issue list filtered to that type).
- **Document status**: healthy, degraded, broken, pending, orphaned, each opening Documents filtered to that status.
- **Top open issues**: the six worst, each opening its detail panel. **Tenant health**: documents, healthy count and score per tenant.
  **Last audit**: issues opened, reopened, escalated, resolved, unchanged, and retrieval probes run. **Connection health**: one line per
  system, checked live, with response time.

### Data Sources
The three systems that are compared: **Amazon S3** (the documents), **PostgreSQL** (the manifest) and **Qdrant** (the vector index), plus a
read-only **Issue ledger** status. Until all three are configured a guide at the top walks through *1 Source, 2 Manifest, 3 Index*.
- Each card shows its state (*Connected*, *Not connected*, *Error*), what the server measured just now (for example "bucket reachable,
  hash mode metadata", response time), the key non-secret settings, and when it was saved and last tested.
- **Configure** / **Edit** opens a form for that group (the fields are listed in section 5). **Test connection** checks what is typed
  without saving it and shows one line per check (for example "Qdrant reachable: 1 collection", "Payload: found `document_id` and
  `source_hash`"); **Save** stores it (secrets are encrypted and never shown again); **Test** on the card checks what is saved and
  remembers the result.
- A **Refresh status** button re-checks all connections. On a single-user server the cards are read-only and say the connections come
  from the server's `RAGI_*` environment variables.
- **Setup check** card (below the three cards once all three are saved; always on a single-user server; no menu item): a **Check setup**
  button (**Check again** afterwards) that calls `POST /api/setup-check` (section 3.10) and shows, while it works, a spinner and "Reading your
  three systems" (up to about two minutes). The result: a banner coloured by the verdict (**Ready**, **Almost ready**, **Not ready yet**) with
  the server's `headline`; three coverage tiles (*S3 documents found in the manifest*, *Manifest rows with a file in S3*, *S3 documents found in
  Qdrant*; green from 80%, amber from 20%, red below, **n/a** when nothing could be compared); **What to do next** (`next_steps`); **The
  checks**, problems first (red before amber) and the rest collapsed into "N checks passed or not applicable", each row with its badge
  (**Passed**, **Worth a look**, **Needs fixing**, **Not applicable**), `detail`, `examples` in monospace, `hint`, then **What to do** (`fix`);
  **IDs at a glance** (five IDs each from S3, the manifest and Qdrant, side by side, with how Qdrant stores them); and quiet notes (what was
  read, `limits`, when and how long). The texts are the server's, shown unchanged. A `pass` row such as *Qdrant against S3* is information.
  A 429 (more than 20 checks in 10 minutes) shows the server's message with **Try again**.

### Reconciliation
The three-way comparison and its results.
- **Run full audit**, **Scoped audit** (choose one tenant, and whether to probe retrieval for the worst findings) and **Export report**
  (Markdown, CSV or JSON).
- **Three-way comparison**: source documents, manifest rows and index vectors from the latest full audit, with the real differences in
  one line each.
- **Results of the latest full run**: findings in total, by severity and by type (each opening the issue list), and what changed since
  the previous run.
- **Documents**: every document the last audit compared, with tabs *All, Healthy, Needs attention, Orphaned, Pending*, search and a
  tenant filter. Three icons show whether the document is present in the source, the manifest and the index. Click a row to open it.

### Integrity Issues
Three tabs: **Issues**, **Repair plans**, **Impact analysis**.

**Issues.** Severity chips (click to filter), then search, **Status** (Open, Resolved, Ignored, All), **Severity**, **Type** and **Tenant**.
Columns: *Severity, Issue, Document, Status, First seen, Last seen, Seen*. Tick rows to **Create repair plan** or **Ignore** several at
once. Click a row for the detail panel:
- **What's wrong** (the plain-language detail) and **Why it matters** (what the finding means for your users);
- **Expected vs actual** side by side, written from the stored evidence;
- **Affected systems** (S3, PostgreSQL, Qdrant) and a link to the document;
- **Evidence**: the values the audit read, the retrieval probe (whether the content is returned for a matching query, at what rank and
  score, which results are stale), the problems list for metadata findings, the missing chunk ids and the number of removal
  candidates; the raw evidence is available in a collapsible section;
- **Recommended fix** (section 6) and a **Timeline** (opened, severity changed, resolved, reopened, ignored);
- buttons: **Create repair plan**, **Ignore** (asks for a reason, kept in the audit trail) or **Reopen**, and **View document**.

**Repair plans** (how problems get fixed safely: section 7).
- **Recommended work**: documents to reprocess, chunks to regenerate, estimated tokens and cost, the saving compared with re-embedding
  everything, and superseded vectors that can be removed later, with the pricing assumptions in small type. Pick a minimum severity and
  press **Create plan from recommendations**.
- **Repair plans** lists every plan with its status. A plan opens in a panel with a summary, **Where this stands** (what happens next,
  and a warning with a **Set up the repair webhook** link when none is configured), the documents with what will happen to each and
  whether it was verified, and a **History**. The buttons follow the plan's state: **Trigger repair** (sends the signed webhook),
  **Verify now** (re-checks the real index), **Send repair again** (for a partial or failed plan), **Approve cleanup** (a confirmation
  states exactly how many vectors will be removed, and that it cannot be undone) and **View payload** (the exact signed body).

**Impact analysis** (section 8): choose *Open issues*, *Pipeline change* (the parser, chunking or embedding model you plan to move to) or
*Ingestion failure* (when it started), then **Analyze impact**. It returns documents and tenants affected, the work and cost to fix, and
the queries that touched them (from your retrieval log, last 14 days).

### Isolation
Whether your index keeps tenants apart (the idea is in section 3.9). Everything on the page is read-only and comes from the latest **full**
audit; a scoped audit does not change it. The header has **Download evidence report (.md)** and **Run isolation drill**.
- **Status banner**: one sentence from the server, coloured by seriousness, with how long ago the audit finished and a **View audit** link.
  Titles: **Leak found** (red), **Needs attention** (amber), **No leaks found** (green), **This check is limited** (blue) and
  **Only one tenant** (grey).
- **Six cards**: *Tenants*, *Vectors checked*, *Documents under the wrong tenant*, *Confirmed reachable by a search* (how many of those a
  live search returned; the line under it says how many wrong-tenant documents were searched at all, up to 25 per audit, or that
  reachability is unknown when none was), *Tenant labels* and *Permission labels* (the share of vectors that carry each label;
  **Not recorded** when the index records no permissions, and a line says how many documents differ from the manifest).
- **Checks**: the five checks of section 3.9, each *Passed*, *Warning*, *Failed* or *Not applicable* (*Not checked* when the result is
  limited), with a detail line. A check that was not run says why ("Not checked: ..."). The reachability check shows *Warning* when no leak,
  or only some, was searched, and *Passed* only when every leak was searched and none was returned.
- **Tenants**: worst first, with a search box. Columns: *Tenant, Status* (Leak, Needs attention, Clean, Single tenant; **Not fully
  checked** instead of Clean when limited), *Documents, Vectors, Tenant label, Permission label, Foreign documents, Permission
  mismatch*. At most 200 tenants are listed ("Showing the worst N of M tenants"). A row opens Documents filtered to that tenant.
- **Open findings (live)**: the issues open right now, which are the open **Tenant mismatch** issues and the open **Metadata mismatch**
  issues that include `acl_mismatch`. Columns: *Severity, Issue, Tenant, Document, Status*. A row opens the issue panel. The banner, cards
  and checks come from the last full audit but this list is live; when they no longer agree (after a scoped re-audit, an ignore or a
  repair) a note says "These changed since the last full audit. Run a full audit to refresh the summary above." Two links open Integrity
  Issues filtered: **Wrong-tenant issues** (Tenant mismatch) and **Permission mismatches** (Metadata mismatch).
- **Run isolation drill**: a dialog marked **DRILL** that starts at once. It shows the **Document used**, **What the drill pretended**,
  **The audit caught it**, **What the audit would raise**, the **Alert it would have sent** (the real Slack-style message an audit would
  post to your alert webhook, with a note that the drill never sends it) and a confirmation that nothing was written, saved or sent;
  **Run it again** repeats it. It never changes anything, so it works in every state.
- **Download evidence report (.md)** saves `rag-isolation-report.md`: the result, the checks, the tenants and the open findings, marked as
  generated read-only (a percentage with nothing to measure is written `n/a`). It is disabled until a full audit has produced a result.
- **Limited**: with **Only audit documents found in the source (S3)** on, vectors under another tenant are never read, so a **Why this
  check is limited** card says so (and links to **Open audit policy settings**), the two leak cards read **Not checked**, and the drill
  still works. The card says a full check has to read the whole index and can run past the time limit on a large one, so it recommends
  `ragi audit` on your own computer and turning the switch off on the hosted site only when the index is small (self-hosted: run
  `ragi audit` with `RAGI_SOURCE_DOCUMENTS_ONLY=false`, or set it to false on the server only when the index is small). A **Tenant labels**
  figure of 0% carries the hint that the payload has no tenant field, so every vector counts as the default tenant.
- **Only one tenant** (*not applicable*): a card says there is nothing to compare; the two leak cards read **Not applicable**.
- Before the first full audit the page shows **No isolation result yet** with a **Run full audit** button; a workspace that has not
  connected its three systems sees **Connect your data first**.

### Documents
Every document with its state. Cards count *Total, Healthy, Needs attention, Orphaned, Pending* (each filters the table). Filters:
search by document id, status, tenant. Columns: *Document, Tenant, Embedding status* (Healthy, Stale, Missing embeddings,
Processing, Failed), *Source* and *Indexed* version (a warning when the index was built from a different version), *Chunks* (indexed
over expected), *Size*, *Issues*, *Verified*. Click a row for the panel, which has the buttons **Re-audit document** and **Create repair
plan**, and three tabs:
- **Overview**: status, source URI, hashes and versions, collections, manifest status, the pipeline fingerprint, and whether the
  document is present in the source, the manifest and the index;
- **Chunks**: press **Inspect live** to re-read the document right now from S3, the manifest and Qdrant, and see each expected chunk
  with its class (*fresh, stale, outdated, unknown, orphan*) and how many copies exist;
- **Issues**: this document's findings, each opening its own panel.

### Audit History
Two tabs. **Audit runs**: every audit with when it started, its type (full, scoped, verify), trigger, scope, status, duration, documents,
issues, health and what changed; click a run for its page (stats, **Warnings about document IDs** when the run recorded `stats.warnings` (an amber card with each warning's
detail, **What to do** and a table of example IDs with where their copies are, plus a **Run the setup check** link), what it opened and
resolved, alert delivery, the error if it failed).
**Activity log**: one chronological trail of issue events, repair events and audits, filterable by kind and searchable.

### Integrations
- **Repair webhook** (the *Repair worker* group): where RAGGuard sends signed repair requests, with the flow explained and the exact
  headers your worker receives.
- **API keys**: create (the token is shown once, with a copy button), see when each was last used, and revoke. Keys work only inside
  their workspace: they can run audits and read results, but cannot read settings, create keys or change passwords.
- **REST API**: the base address, to use together with an API key.
- **Connected systems**: the three connections at a glance.
- *Slack*, *Jira* and *PagerDuty* are marked **Not available yet** (use the alert webhook to forward findings today).

### Alerts
The *Alerts* group (email setting, webhook address and minimum severity), an explanation of when alerts are sent and what they contain, and **Recent
deliveries** from your audits (issues included, whether it was delivered, the reason or error). The group also has **Email me**
(always, attention or never). *Per-issue-type rules* and *quiet hours* are marked **Not available yet**.

### Notifications and the bell
The **bell** at the top right shows how many notifications are unread and opens a panel with the latest ten and the next-step buttons; **See all
notifications** opens the **Notifications** page (`/notifications`, reached from the bell and from the emails; it is not a menu page). The same
buttons work in both places (3.14).

### Settings
Tabs: **General** (workspace, account email, server mode and version, and **Change password**, which signs out your other devices; on
the demo server a **Reset demo data** button), **Pipeline** (the *Target pipeline* group), **Policy** (the *Audit policy* group),
**Security** (how secrets are handled, with *two-factor authentication* and *single sign-on* marked **Not available yet**), **Team** and
**Billing** (both **Not available yet**).

*Single-user modes (demo / live) need no sign-in; their Data Sources, Integrations, Alerts and Settings pages are read-only because
the configuration comes from the server's environment.*

### Every checkbox, switch and radio button
Only a handful of controls are tick-boxes; everything else is a drop-down, a clickable severity chip, a tab, a text box or a button.

| Control | Where | What it does |
|---|---|---|
| Row checkboxes, and the header checkbox "Select all N issues" | Integrity Issues, *Issues* tab | Tick issues, then **Create repair plan** (open issues on a specific document only) or **Ignore** them together. |
| **Probe retrieval for the worst findings** (switch, on by default) | Reconciliation, **Scoped audit** | Also queries the live index to confirm that the most serious findings really affect search results. Slower, more convincing. |
| **Detect empty embeddings** (switch, off by default) | Data Sources, Qdrant card, **Configure** / **Edit** | Also fetches the vectors to find empty or all-zero embeddings. Slower and heavier for Qdrant. |
| **Only audit documents found in the source (S3)** (switch, off by default) | Settings, *Policy* tab | The S3 key pattern decides which documents count; manifest rows and vectors for anything else are ignored, and only the matching Qdrant points are read (section 5.7, 5.10). |
| **Scenario**: *Open issues*, *Pipeline change*, *Ingestion failure* (radio buttons) | Integrity Issues, *Impact analysis* tab | Chooses which what-if to analyse (section 8). |

A switch only takes effect after **Save**.

---

## 5. Settings: every group and every field

Three groups are **required** before the first audit: S3, Manifest and Qdrant. The other four are optional tuning.
**Where each group lives in the interface:** S3, Manifest and Qdrant are on **Data Sources**; Repair worker is on **Integrations**;
Alerts is on **Alerts**; Target pipeline and Audit policy are on **Settings** (tabs *Pipeline* and *Policy*); API keys are on
**Integrations**. Every group is saved separately with **Save**. **Test connection** checks what is typed in the form without storing it
(for the Repair worker and Alerts groups the button is **Check settings**: it validates the values and sends nothing), and **Test** on a
Data Sources card re-runs the real connector against what is saved and remembers the result.

How secrets behave: a field marked **secret** is encrypted at rest, is **write-only** (after saving it shows "saved" and the value never
comes back), leaving it empty keeps the stored value, and **Remove saved value** deletes it. Empty non-secret fields fall back to the default shown.
Every host or URL you enter must be a **public** address (section 13).

### 5.1 Source documents (S3)
Where your documents live. Read-only: `list` and `head`, plus `get` only in `compute` hash mode. Works with AWS S3 and S3-compatible
stores (Supabase Storage, MinIO, Cloudflare R2).

**Permissions.** On AWS, `HeadObject` is authorised by the `s3:GetObject` permission, so the key needs **both** `s3:ListBucket` (on the
bucket) and `s3:GetObject` (on its objects). Both are read-only and nothing is ever written. Only an `etag`-mode audit can run on
`s3:ListBucket` alone, and even then "Test connection" and repair verification still send HEAD requests.

**How to connect S3, step by step**
1. In AWS: *IAM > Users > Create user*, then attach this policy (replace `YOUR-BUCKET`):
   `{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:ListBucket","Resource":"arn:aws:s3:::YOUR-BUCKET"},{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::YOUR-BUCKET/*"}]}`
2. Open that user's *Security credentials* tab, press *Create access key*, and copy the **Access key ID** and **Secret access key** (shown once).
3. Note the bucket's **region** (for example `ap-south-1`) from the S3 console.
4. In the app: sign in, open **Data Sources**, press **Configure** on **Amazon S3** and fill **Bucket**, **Region**, **Access key ID** and **Secret access key**.
   Leave **Custom endpoint** empty for AWS.
5. Check how your keys look. The default **Key pattern** expects `tenant/path/to/document.pdf`. For a flat bucket with no tenants set it to
   `^(?P<document_id>.+)$`; to audit only a folder set **Key prefix**.
6. Press **Test connection**, then **Save**. Every line should say OK; a warning or failure names exactly what to change.
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
| **Look up files from the manifest (skip listing the bucket)** | no | no | off | For large buckets. Instead of listing every object, the audit reads exactly the files named in the manifest's `source_uri` column (S3 addresses such as `s3://bucket/key` or `https://bucket.s3.region.amazonaws.com/key`), one HEAD request each, keeping only files in this bucket whose key matches the **Key pattern**. Cost no longer grows with the size of the bucket. Trade-off: a file that is in S3 but not in the manifest is not discovered. Needs the manifest's `source_uri` to be mapped (section 5.2). Also keeps one-document checks (**Re-audit document**, the isolation drill) fast, because the manifest is asked for just that document. |

**Important:** whatever hash you use here, your pipeline must record the **same value** as `source_hash` in the manifest and in each
Qdrant payload, otherwise every document will look stale.

**What "Test connection" checks (S3):** *Bucket reachable* (lists up to 200 keys under the prefix and explains common errors: no such bucket,
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

**What "Test connection" checks (manifest):** *Database reachable* (explains bad password, timeout, unresolved host, SSL); *Manifest table* (found, how many of the 21 columns are mapped); *Columns used for checks* (warns when `source_hash`, `processing_status`, `expected_chunk_count` or `indexed_chunk_count` are missing); *Rows* (up to 100,000+); *Role is read-only* (warns if your role can write); *Chunk manifest*.

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

**What "Test connection" checks (Qdrant):** *Qdrant reachable* (explains a rejected API key, timeout, unresolved host, refused connection);
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
| **Email me** | no | `always` | `always`, `attention` or `never`: when the email after an audit is sent (3.14). The notification in the app is always created. |
| **Webhook URL** | **yes** | none | A Slack-compatible incoming webhook (JSON with a `text` field). Treated as a secret because Slack webhook URLs are. |
| **Minimum severity** | no | `high` | `critical`, `high`, `medium` or `low`. Only **new, reopened or escalated** issues at or above it are sent, so a steady state is silent. |

### 5.7 Audit policy (optional)
| Field | Default | Meaning |
|---|---|---|
| **Grace period (minutes)** | 10 | 0 to 1,440. Documents modified or being processed within this window are `pending`, not broken. |
| **Default tenant** | `default` | Assumed when a Qdrant payload or manifest row has no tenant. |
| **Required payload fields** | empty | Comma-separated. Empty means `document_id` and `source_hash`, plus `tenant_id` once more than one tenant exists. A vector missing a required field raises a metadata finding. |
| **Only audit documents found in the source (S3)** | off | When on, the S3 inventory defines the corpus (the **Key pattern** chooses which files count). Manifest rows and vectors for any other document are ignored, and only the matching Qdrant points are read with a server-side filter instead of scanning the whole collection. Use it when the manifest or the index is shared with more than the bucket covers. Trade-off: left-over vectors (`orphan_vector`), manifest rows for deleted files (`manifest_orphan`) and wrong-tenant vectors (`tenant_mismatch`) are then not reported. |
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
| s3 | Look up files from the manifest (skip listing the bucket) | `lookup_from_manifest` | `RAGI_S3_LOOKUP_FROM_MANIFEST` | on/off |
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
| alerts | Email me | `email_when` | `RAGI_ALERT_EMAIL_WHEN` | always / attention / never |
| alerts | Webhook URL | `webhook_url` | `RAGI_ALERT_WEBHOOK_URL` | URL, secret |
| alerts | Minimum severity | `min_severity` | `RAGI_ALERT_MIN_SEVERITY` | critical / high / medium / low |
| policy | Grace period (minutes) | `grace_minutes` | `RAGI_GRACE_MINUTES` | integer |
| policy | Default tenant | `default_tenant` | `RAGI_DEFAULT_TENANT` | text |
| policy | Required payload fields | `required_payload_fields` | `RAGI_REQUIRED_PAYLOAD_FIELDS` | comma list |
| policy | Only audit documents found in the source (S3) | `source_documents_only` | `RAGI_SOURCE_DOCUMENTS_ONLY` | on/off |
| policy | Embedding price (USD per 1M tokens) | `embedding_price_per_mtok` | `RAGI_EMBEDDING_PRICE_PER_MTOK` | number |
| policy | Tokens per chunk (for estimates) | `chunk_size_tokens` | `RAGI_CHUNK_SIZE_TOKENS` | integer |

In `app` mode a workspace's unset fields use the defaults above and **never** the server's environment, so one deployment's environment
cannot leak into a user's connections.

### 5.10 Worked example: audit only part of a shared index (bills)
**The situation.** S3 holds `bills/<bill number>/<document number>.pdf`. The manifest table `bill_documents` has `external_bill_id`,
`external_doc_id`, `s3_url` and a true/false `is_indexed`. One Qdrant collection, `bill_chunks`, holds millions of points from many
states and years; each point names its bill in `source_id`, and some also carry `doc_version`.

**What lines up.** For the `prefiled` documents the file name equals the folder name, and `external_doc_id`, `external_bill_id` and
Qdrant's `source_id` are the same number, so those documents can be audited exactly. For every other document type Qdrant only knows
the bill (its `doc_version` did not match `external_doc_id`), so they cannot be matched one to one.

| Where | Setting | Value |
|---|---|---|
| S3 | Bucket / Region | `billflo-ai-development` / `us-west-1` |
| S3 | Key prefix | `bills/` |
| S3 | Key pattern | `^(?P<document_id>[^/]+)/(?P=document_id)\.pdf$` (folder name equals file name, so only those files count) |
| S3 | Content hash | `etag` (Qdrant has no `source_hash` to compare with anyway) |
| S3 | Look up files from the manifest (skip listing the bucket) | on (the bucket holds far more than these documents, and the manifest already names each file in `s3_url`) |
| Manifest | Document table | `bill_documents` |
| Manifest | Column map | `{"document_id":"external_doc_id","source_uri":"s3_url","processing_status":"is_indexed"}` |
| Qdrant | Collections | `bill_chunks` |
| Qdrant | Payload field map | `{"document_id":"source_id"}` (do not map `tenant_id`; S3 and the manifest have no state) |
| Audit policy | Only audit documents found in the source (S3) | on |

**What it reports.** A document with a file in S3 and no points in Qdrant is `missing_embedding`, **critical** when `is_indexed` is
true (the pipeline claimed success), otherwise high. Duplicate chunks, empty embeddings and metadata problems are found as usual.

**What the setup check shows for this layout.** S3 against the manifest passes (every `prefiled` file has a manifest row), Manifest against
S3 warns that most manifest rows have no file here (the other document types), and Qdrant against S3 notes that most of the sampled points belong to
other bills; with **Only audit documents found in the source (S3)** on, as above, that last one passes because those points are ignored. Run it
after changing any setting in this table.

**What it cannot report here.** Changed files (no `source_hash` in Qdrant or the manifest), half-indexed documents (no chunk counts),
and left-over vectors for deleted files (switched off by the option, because the collection holds far more than the bucket).

**Speed.** Only the points of the listed documents are read, using a server-side filter on `source_id`. If Qdrant is in strict mode it
refuses to filter on a field without a payload index (the message says so); ask the cluster owner to create a keyword index on
`source_id`. On the hosted site an audit has 270 seconds (the function limit is 300 s) and one Qdrant request may take at most 60
seconds, so a slow unindexed filter fails with a clear message ("Qdrant timed out ... create a keyword index") instead of hanging.
Listing a very large bucket is the other slow step: switch on **Look up files from the manifest**, which needs only one request per
listed file. While a run is working it records its current step, so a run that is ever cut off still shows where it stopped (Audit
History, "last step: ..."). For a corpus too large even for that, run `ragi audit`.

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
current but the manifest records an older hash), `manifest_version_mismatch` (low), `status_failed_but_indexed` (low), `chunk_hash_mismatch` (medium: chunks carry a different hash than the chunk
table records although the document hash says the index is current; see 3.11), and
`unattributed_vectors` (high, collection-level: points with no document id).

**Recommended actions:** `reindex_full` re-process the whole document; `reindex_chunks` re-embed only the missing chunks;
`cleanup_vectors` remove superseded vectors, only after replacements are verified; `fix_metadata` correct the manifest or payload
(no re-embedding); `investigate` needs a human.

---

## 7. The repair workflow

The platform holds **read-only** access and never deletes vectors blindly. Repair is a hand-off with independent verification.

1. **Plan.** Open issues are grouped per document into the *smallest safe action*: `reindex_full` for missing, stale, drifted or empty-embedding documents; `reindex_chunks` for partial indexes; `fix_metadata` when only metadata is wrong; and a "cleanup later" flag for superseded, duplicate, orphan and tenant-mismatch vectors. Collection-level findings are not document repairs.
2. **Trigger.** The reindex request is POSTed to your webhook, signed with HMAC-SHA256 over `"<timestamp>.<raw body>"` (headers `X-Ragi-Event`, `X-Ragi-Timestamp`, `X-Ragi-Signature`, `X-Ragi-Delivery`; a 5-minute replay window). **Reindex phase: add or replace only, never delete.** Without a signing secret nothing is sent. A failed delivery is reported without the webhook address (it is a secret: Slack puts its token in the path).
   **A plan that only removes vectors** (orphans, duplicates, superseded or wrong-tenant vectors) has nothing for your worker to reprocess:
   **Trigger repair** sends nothing, records a `nothing_to_reindex` event and goes straight to verification, so the plan becomes
   `cleanup_pending` and is ready for **Approve cleanup**. Verify can also be the first step of such a plan.
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
| GET | `/` | public | the web interface (any other page address that is not under `/api`, `/static`, `/docs` or `/redoc` also returns it, so deep links and refresh work) |
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
| POST | `/api/deletion-check` | session or key (20 per 10 min per workspace in the hosted app) | verify deleted documents: remaining vectors, a search test, the verdict and the advice; body `documents` (optional) and `record` (default true) (3.13) |
| POST | `/api/setup-check` | session or key (20 per 10 min per workspace in the hosted app) | the read-only setup and coverage check: do S3, the manifest and Qdrant use the same document IDs (3.10) |
| POST | `/api/audits` | session or key | run an audit (`tenant`, `documents`, `probe`, `wait` options; `resume: true` continues the last partial audit; the status can be `partial`, see 3.12) |
| GET | `/api/audits` | session or key | recent runs |
| GET | `/api/audits/{run_id}` | session or key | one run |
| GET | `/api/notifications` | session or key | the workspace's notifications, newest first, and how many are unread; `limit`, `unread` (3.14) |
| POST | `/api/notifications/read-all` | session or key | mark every notification read |
| POST | `/api/notifications/{notification_id}/read` | session or key | mark one read |
| POST | `/api/notifications/{notification_id}/done` | session or key | remember that one of its buttons was pressed; body `action` must be the id of one of its buttons |
| GET | `/api/issues` | session or key | list issues (filters `status`, `severity`, `type`, `tenant`, `q`, paging) |
| GET | `/api/issues/{issue_id}` | session or key | one issue with its timeline |
| POST | `/api/issues/{issue_id}/ignore` | session or key | ignore with a reason |
| POST | `/api/issues/{issue_id}/reopen` | session or key | reopen an ignored issue |
| GET | `/api/documents` | session or key | document states (filters and paging) |
| GET | `/api/document` | session or key | one document; `live=true` adds the three-way source/manifest/index view |
| GET | `/api/report` | session or key | the integrity report (`format=json\|md\|csv`) |
| GET | `/api/isolation` | session or key | tenant isolation as of the latest full audit: overall and per-tenant status, five checks, open findings (`available: false` before the first full audit) |
| GET | `/api/isolation/report` | session or key | the isolation evidence report (`format=json\|md`) |
| POST | `/api/isolation/drill` | session or key | the read-only isolation drill on one document (body `tenant` and `document_id`, both or neither) |
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
| `ragi serve [--host H] [--port P] [--demo] [--app]` | run the API and web interface (default `127.0.0.1:8000`); `--demo` the synthetic world, `--app` the multi-user mode |
| `ragi demo [--seed N]` | seed the demo world and audit it, print a summary |
| `ragi audit [--tenant T] [--no-probe] [--resume] [--json] [--fail-on SEVERITY]` | run an audit now; with `--fail-on` it exits **2** if open issues at or above that severity remain (cron/CI gating); `--resume` continues the last partial audit; it exits **3** when the audit ends partial (3.12) |
| `ragi verify-deletions [--document ID] [--tenant T] [--no-record] [--json]` | verify deleted documents (3.13); `--document` is repeatable (`TENANT/ID`, or an id with `--tenant`); exits **1** when vectors remain |
| `ragi issues [--status S] [--severity S] [--type T] [--tenant T] [--limit N]` | list issues from the ledger |
| `ragi report [--format md\|json\|csv] [--all] [-o FILE \| --output FILE]` | the document-level integrity report |
| `ragi connections` | test the ledger, S3, the manifest database and Qdrant, naming whichever is misconfigured |
| `ragi setup-check [--json]` | the setup and coverage check (3.10): do S3, the manifest and Qdrant use the same document IDs; exits **1** when the result is `not_ready` |
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
| `RAGI_MAX_AUDIT_SECONDS` | `0` | audit time budget; `0` is unlimited, and 270 is implied on serverless. |
| `RAGI_SYNC_AUDITS` | `false` | run audits inside the request (implied on Vercel). |
| `RAGI_PROBE_RETRIEVAL`, `RAGI_PROBE_MAX`, `RAGI_PROBE_TOP_K` | `true`, `25`, `10` | retrieval-probe switches and limits. |
| `RAGI_AUDIT_SLICE_DOCUMENTS` | `5000` | documents per slice of the index when only the source's documents are audited; each finished slice is a checkpoint (3.12). |
| `RAGI_SMTP_HOST`, `RAGI_SMTP_PORT`, `RAGI_SMTP_USER`, `RAGI_SMTP_PASSWORD`, `RAGI_SMTP_FROM`, `RAGI_SMTP_SECURITY` | none, `587`, none, none, none, `starttls` | the platform's one mail account, which sends every workspace's alert emails (3.14). `RAGI_SMTP_SECURITY` is `starttls`, `ssl` or `none`. No host and sender means no email. |
| `RAGI_APP_URL` | none | the public address of this deployment; the links in emails point here (on Vercel the production address is used when this is unset). Never taken from a request. |
| `RAGI_ALERT_EMAIL_TO` | none | single-user modes only: who gets the email, comma-separated. App mode emails each workspace's own users and ignores it. |
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
| `audit_runs` | id, workspace_id, kind, trigger, scope, status, started_at, finished_at, stats, error | each audit; `status` is `running`, `completed`, `partial` or `failed` (3.12); a unique index allows one `running` per workspace |
| `issues` | workspace_id, id, type, severity, status, tenant_id, document_id, collection, title, detail, evidence, action, first_seen_at, last_seen_at, first_run_id, last_run_id, resolved_at, resolved_run_id, occurrences, reopened_count, ignored_reason | the issue ledger |
| `issue_events` | id, workspace_id, issue_id, run_id, ts, event, details | issue lifecycle trail |
| `documents` | workspace_id, tenant_id, document_id, status, issue_count, worst_severity, issue_types, fingerprint, source_uri, source_hash, source_version, size_bytes, expected_chunks, indexed_chunks, manifest_status, manifest_updated_at, collections, source_present, manifest_present, index_present, last_verified_at, last_run_id, indexed_version | the latest verified state of every document |
| `repair_plans` | id, workspace_id, status, created_at, updated_at, items, summary | repair plans |
| `repair_events` | id, workspace_id, plan_id, ts, event, details | repair trail |
| `query_log` | id, workspace_id, ts, tenant_id, query_hash, retrieved_doc_ids | retrieval logs (query text hashed, never stored) |
| `notifications` | id, workspace_id, created_at, kind, tone, title, body, details, run_id, actions, read_at, done_action, emailed_at | what each audit told the workspace and the buttons it offered; the newest 200 are kept (3.14) |

`workspace_id` is on every ledger table and every query is filtered by it (section 13).

---

## 13. Security model

The full threat model, with what is and is not covered, is in [docs/security.md](docs/security.md). In short:

- **Passwords**: scrypt with a per-user salt, constant-time compare; unknown emails burn the same CPU, so timing does not reveal accounts.
- **Sessions**: a random 256-bit token in an `HttpOnly`, `SameSite=Lax`, `Secure` cookie; only its SHA-256 is stored; 7-day sliding expiry; logout and password change revoke on the server.
- **CSRF**: `SameSite=Lax` plus an `Origin` check on every cookie-authenticated write.
- **Rate limits** (database-backed, so they hold across serverless instances): 8 sign-in attempts per account and 30 per network per 15 minutes; 5 sign-ups per network per hour; 10 password changes per account per 15 minutes; 30 connection tests per workspace per 10 minutes; 20 setup checks and 20 deletion checks per workspace per 10 minutes.
- **Tenant isolation**: every ledger statement carries the workspace id; the tests attack read, modify, resolve, reset and plan-hijack across workspaces, on SQLite and a real Postgres.
- **Secrets at rest**: Fernet (AES-128-CBC + HMAC-SHA256) under `RAGI_SECRET_KEY`, which exists only in the server environment. Secrets are write-only in the UI/API. Errors and ledger rows are scrubbed of `scheme://user:password@host` credentials, and the error of a failed alert or repair webhook delivery has every web address removed (a webhook address is itself a secret), in the ledger, the logs and the interface. That includes the target of a redirect (even a relative one) and the host, path, query and user info of the configured address wherever a library echoes them without the scheme; run rows stored before this existed have any web address removed when they are read.
- **SSRF guard**: every host a user supplies (S3 endpoint, Qdrant URL, manifest database, repair and alert webhooks) must be public. Loopback, private, link-local (including the cloud metadata address), carrier-grade NAT, IPv4-mapped IPv6, multicast and reserved ranges are refused; hostnames are resolved and every address must be public; checked when saved **and again before every connection**. URLs may not contain credentials; databases must be `postgresql://` with only `sslmode`, `connect_timeout`, `application_name` options.
- **Read-only connectors**: S3 list/head (get only in `compute` mode); manifest queries in `READ ONLY` transactions; Qdrant scroll/retrieve/query.
- **API keys** are hashed, revocable, and cannot read settings or mint keys.
- **Web hardening**: strict `Content-Security-Policy` (`script-src 'self'`), `X-Frame-Options: DENY`, `nosniff`, no referrer, `no-store` on API responses; the web interface renders every value as text (React escapes it; there is no raw HTML anywhere) (document ids come from S3 keys, so they are untrusted).

**Not covered:** no email verification or password reset (the mail account only sends audit alerts), no two-factor authentication, no teams or roles, and the DNS-rebinding window between validation and connection is narrow but not zero.

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
| `vercel.json` | `maxDuration` 300 s and bundles `src/**`. **No rewrites** (a catch-all rewrite makes every route 404). |
| `requirements.txt` | the only install source on Vercel (FastAPI, SQLAlchemy, psycopg, httpx, boto3, qdrant-client, cryptography) |
| `.vercelignore` | hides `pyproject.toml`, tests, docs, `.env*` from the upload |
| `supabase/migrations/20261107000000_ragi_ledger.sql` | v1 ledger |
| `supabase/migrations/20261108000000_multi_user.sql` | v2 accounts and workspace-scoped ledger; **refuses to run if the old tables hold data** |
| `supabase/migrations/20261109000000_documents_indexed_version.sql` | adds the indexed version of each document |
| `supabase/migrations/20261110000000_notifications.sql` | the notifications table (the app also creates it itself on start-up) |
| `scripts/vercel-env.ps1` | sets the two secrets on Vercel (run by you; writes exact bytes: no BOM, no newline) |
| `Dockerfile`, `docker-compose.yml` | container image and a full local stack (MinIO, Postgres, Qdrant, seed, reference worker, app) |
| `.github/workflows/ci.yml` | tests against Postgres, Qdrant (API key enforced) and S3 over HTTP; image build and push |

### 14.3 Setup recap
1. `npx vercel login`, then `npx vercel link --project rag-integrity-platform`.
2. `supabase link --project-ref <ref>` then `supabase db push` (14 tables, RLS on).
3. Put `RAGI_DATABASE_URL` in `.env`, run `scripts/vercel-env.ps1` yourself (it generates and keeps `RAGI_SECRET_KEY`).
4. Deploy: `npx vercel deploy --prod`, or push to `main`.

### 14.4 Day-to-day
- **Roll back**: `npx vercel promote <previous-deployment-url>`.
- **Users**: `ragi users list`, `ragi users delete someone@example.com --yes`.
- **Close sign-up**: set `RAGI_ALLOW_REGISTRATION=false`.
- **Rotate the secret key**: set `RAGI_SECRET_KEY` to `new,old`, redeploy; stored secrets keep working and new saves use the new key.
- **Scheduled audits**: serverless has no scheduler. Create an API key on Integrations and call `POST /api/audits` from GitHub Actions or cron.
- **Large corpora**: audit per tenant, or run `ragi audit` outside serverless.

### 14.5 The practice lab (learn it on your own computer)
`docker compose -f docker-compose.lab.yml up --build` starts a private S3 (the fake-S3 server "moto"), PostgreSQL and Qdrant on your computer, fills them with
**30 documents that carry every kind of fault, planted once each**, and runs two copies of the app: **Lab A** (http://localhost:8000, live
mode, already connected, with the reference repair worker so you can run the whole fix loop) and **Lab B** (http://localhost:8001, the
multi-user app, empty, for practising sign-up and entering the settings of a "bills" setup like a real customer). Lab A also holds three
documents whose Qdrant ID is a number, a decimal and text, and one duplicated manifest row. `lab/WORKBOOK.md` is the answer sheet (generated
by running the real audit on the lab, and checked by a test); `lab/README.md` is the step-by-step guide. The lab reads no `.env`, binds every
port to 127.0.0.1, keeps a throwaway ledger inside each container, and its seeding script refuses any address that is not local.

---

## 15. Verification status

**Verified** (and how):
- **569 tests.** On a plain checkout with no external services **529 pass and 40 skip** (checked before publishing). The 40 skipped need real servers; with a real local Qdrant (API key enforced), S3 over HTTP and Postgres attached, the 40 real-service tests (Qdrant 16, S3 over HTTP 5, end-to-end connectors 4, Postgres 9, and 6 scenarios that use all three) all pass, so all 569 pass. Per file: accounts 22, api 31, app connectors 4, app mode 46, audit notifications 32, big corpus 15, connectors 19, deletion verification 22, docs 16, duplicate ids 13, edge cases end to end 6, engine 11, help pages 8, id types 47, isolation 28, lab 22, landing scenarios 4, live mode 6, Postgres integration 5, real Qdrant 10, reference worker 3, repair cleanup only 5, S3 over HTTP 5, scan reliability 39, schema 4, security 26, serverless 8, service 15, setup check 36, source only 13, stuck audits 4, version integrity 23, webhook error leaks 15, webhook errors 6.
- The engine finds **exactly** the injected faults (compared with ground truth) in the in-memory demo *and* through the real connector code.
- A **real Qdrant 1.20 server** (checksum-verified official build, API key enforced): paging past one page, server-side filters, empty-vector detection, probes, wrong-key and unreachable diagnostics, ids stored as numbers and as text found by the same filter, and the setup check against it.
- A **real Postgres engine** (also number, decimal and text ID columns read the same way, including scoped reads): both migrations apply in order and idempotently, RLS on all 14 tables, the destructive migration refuses to drop data, workspace isolation and the one-running-audit index hold.
- **S3 over real HTTP** with a custom endpoint and path-style addressing (inventory, compute hashing, scoped listing, diagnostics).
- **Audit notifications** (`tests/test_audit_notifications.py`): the text and buttons for every way an audit can end; the email going out over a **real local SMTP server** (text and HTML parts, one message per recipient, no header injection, secure connection before login, credentials never echoed); the email only to the workspace's own users; the hourly cap and the fail-closed rule; a mail server that is down, a missing table and a failing notification never failing an audit; and notifications staying inside their workspace over HTTP.
- **Versions, deletions and scan reliability end to end** (`tests/test_edge_cases_end_to_end.py`): real S3 over HTTP, a real PostgreSQL holding the manifest, the chunk table **and** the ledger, and a real Qdrant. A file changed in S3 and re-indexed; a shortened document and a changed chunk hash; a document deleted from S3, proved searchable by a real search, cleaned up and verified; a misbehaving cluster that changes nothing in the answer; a cluster that never recovers (partial, then resumed to exactly the ledger of an uninterrupted audit); and a document deleted between the stop and the resume. The edge cases are listed in `docs/edge-case-report-features-1-2-4.md`.
- The app run against the **real Supabase** with a throwaway account (16 of 16 checks: empty workspace, SSRF refusal, secrets encrypted at rest, API keys, logout, login), then cleaned to zero rows.
- The **live site**: healthy, connected to Supabase, protected endpoints return 401 to anonymous visitors, headers present, sign-in and sign-up screens render in a real browser.

**Not verified:**
- A user's own S3 bucket, manifest database and Qdrant cluster on the live site (none existed to test against).
- Email through a real mail provider (a provider account is the operator's to create). The sending code is tested against a real local SMTP server, with the secure-connection and login order checked.
- The version table, the deletion check and scan resuming against a user's own systems; and a collection of millions of points (the largest measured is 150,000; `scripts/benchmark_scan.py` measures a real cluster read-only).
- `docker-compose.yml` was validated but never run (Docker Desktop could not start on the development machine).
- Registration and login **on the live site itself** were not exercised by automation (account creation there is yours to do); the same flows were tested locally against the real Supabase.

---

## 16. Limits and caveats

- **Scale**: aggregation is in memory, measured at about 19,000 vectors per second and about 600 bytes per vector on a laptop (about 1M vectors is roughly a minute and 600 MB). On Vercel an audit must finish in 270 seconds.
- **S3 hashing**: `metadata` mode costs one HEAD per object. For very large buckets store a SHA-256 in object metadata at upload time.
- **One workspace per user**; no teams, roles, email verification, password reset or two-factor authentication.
- **Collections**: a document is expected in at least one configured collection; per-collection expectations are not modelled.
- **IDs are matched exactly** (apart from number versus text, see 3.1): letter case, spaces, leading zeros, prefixes and extensions all make IDs
  different. One S3 file or manifest row per ID is followed; duplicates are warned about, not merged. The setup check looks at a bounded sample
  (200,000 files, 500,000 rows, 1,000 points, 200 documents looked up in the index), so its percentages for a very large system are estimates.
- **Retrieval probe** replays an affected chunk's own vector, not real user traffic: it proves searchability and rank, not user impact. The deletion check uses
  up to 3 chunks of a document; a document whose other chunks rank lower than 10 can read as not returned although a different query would find it.
- **Resume works in slices.** Only audits of the source's documents are sliced and resumable (3.12); a whole-index scan is one pass. A slice is thousands of
  documents, so a stop loses at most one slice of work. A filtered read of a field without a payload index costs about a pass over the collection per slice.
- **Version evidence depends on the pipeline.** Without a hash or version in the payloads the revision cannot be verified from the index (the verdict says
  `unknown_revision`); chunk hashes and counts are used when the chunk table has them. Preventing out-of-order writes belongs in the ingestion pipeline
  (version-aware writes, conditional activation, fencing); the audit detects the result (`stale_embedding`, `superseded_active`), it does not track job timelines.
- **Deletion checks** find a deleted document only if an earlier audit saw it in the source, the manifest marks it deleted, an issue is open for it, or you name it.
- **Email needs the operator's mail account** (`RAGI_SMTP_*`) and, for links, `RAGI_APP_URL`; the in-app notification does not. Email goes to a workspace's own
  sign-in addresses only (unverified: there is no email verification), at most 12 an hour, and a mail server that is down means no email for that audit.
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
