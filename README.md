<p align="center"><img src="docs/assets/logo.svg" alt="RAGGuard logo" width="88"></p>

# RAG Integrity

**Know when your RAG index is wrong - before your users do.**

RAG Integrity is an independent control plane that audits a production RAG pipeline. It continuously answers one
question:

> *Is the information in my vector database exactly consistent with the latest source data?*

It does **not** replace your ingestion pipeline. It reads your source documents (S3), your processing manifest
(PostgreSQL / Supabase) and your vector index (Qdrant) through **read-only** connectors, reconciles the three, records
every inconsistency with evidence in an issue ledger, and - when you ask it to - hands a repair plan to **your own**
worker and independently verifies the result.

> **Want the complete picture?** [GUIDE.md](GUIDE.md) explains everything that was built: every page of the web interface, every
> Settings group and field, every issue type, the repair workflow, the API, the CLI, the data model, security,
> deployment and what has (and has not) been verified.

```
 Customer infrastructure (read-only access)
 ┌────────────┐   ┌─────────────────────┐   ┌──────────────┐
 │ S3         │   │ PostgreSQL/Supabase │   │ Qdrant       │
 │ documents  │   │ processing manifest │   │ vector index │
 └─────┬──────┘   └──────────┬──────────┘   └──────┬───────┘
       └──────────────┬──────┴──────────────────────┘
                      ▼
        Reconciliation engine  (source  vs  manifest  vs  index)
                      ▼
        Issue ledger (Supabase/Postgres)  ──►  web interface · API · CLI · alerts
                      ▼
        Repair plan ──signed webhook──►  YOUR worker (the only thing that writes)
                      ▲                          │
                      └──── independent verification ◄┘   then approved, verified cleanup
```

## Try it in 60 seconds

```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ragi serve --demo                                        # http://127.0.0.1:8000
```

Demo mode runs a synthetic multi-tenant corpus (~240 documents) with **47 deliberately injected faults**: never-embedded
documents, a pipeline that "succeeded" without writing vectors, stale versions, deleted documents still searchable,
half-indexed documents, retry duplicates, ACL drift, an old embedding model, vectors under the wrong tenant, and more.
Click through *Issues -> Repairs -> Trigger -> Verify -> Approve cleanup* and watch health go from ~84% to 100%.

## The hosted product

**https://rag-integrity-platform.vercel.app**: sign up, then connect **your own** S3 bucket, processing manifest (Postgres) and
Qdrant in *Settings*. There is no sample data: a new workspace is empty until you connect it, and the demo above is for local
exploration only. Each connection has a **Save & test** button that runs the real connector against your infrastructure and
tells you what it found (how many sampled keys match your key pattern, whether objects carry a SHA-256, whether the manifest
columns are mapped and the database role is read-only, which Qdrant collections exist and whether their payloads carry
`document_id` and `source_hash`).

* Accounts, sessions, rate limits, CSRF protection, per-user workspaces and encrypted connection secrets: [docs/security.md](docs/security.md)
* Deployment on Vercel + Supabase, and what serverless changes: [docs/deploy-vercel.md](docs/deploy-vercel.md)
* Run the same multi-user app yourself: `RAGI_MODE=app RAGI_DATABASE_URL=... RAGI_SECRET_KEY=... ragi serve` (or `ragi serve --app`)

Other ways to run it:

| | |
|---|---|
| `RAGI_MODE=app ragi serve` | the multi-user product (needs a Postgres `RAGI_DATABASE_URL` and a 32+ character `RAGI_SECRET_KEY`) |
| `ragi demo` | seed + audit in the terminal, print a summary |
| `docker run -p 8000:8000 ghcr.io/kishore600/rag-integrity-platform` | the demo, containerised (image published by CI) |
| `docker compose up --build` | a **live** stack: MinIO (S3) + Postgres + Qdrant + seeded faults + reference worker + the app |
| `docker compose -f docker-compose.lab.yml up --build` | the **practice lab**: 30 documents with every fault planted once, an answer sheet, and two copies of the app (see [lab/README.md](lab/README.md)) |
| `ragi audit --fail-on high` | one audit from cron / CI; exits 2 if anything at or above `high` remains |

## What it detects

| Issue | Meaning | Default severity | Fix |
|---|---|---|---|
| `missing_embedding` | source document has no vectors | high · **critical if the pipeline reported success** | reindex |
| `partial_index` | only some expected chunks are indexed (names the missing chunk ids) | high · critical if "success" | reindex missing chunks |
| `stale_embedding` | source changed, vectors describe an older version | high | reindex |
| `superseded_active` | new version indexed but old-generation vectors still answer queries | medium · high if retrievable | cleanup (after verification) |
| `orphan_vector` | document deleted at the source, vectors remain | high · **critical if retrievable** | cleanup |
| `duplicate_chunk` | same chunk indexed more than once (retries) | medium | cleanup |
| `metadata_inconsistent` | manifest/payload disagree: counts, ACL hash, versions, missing fields | low-high | fix metadata |
| `pipeline_drift` | indexed with a different parser/chunker/embedding config than the target | medium · high if embedding model/dim | reindex |
| `empty_embedding` | point exists but its vector is missing or all zeros | high | reindex |
| `tenant_mismatch` | vectors tagged with the wrong tenant (cross-tenant leak risk) | **critical** | cleanup |
| `manifest_orphan` | manifest row for a document that no longer exists | low | investigate |

Design points that matter in production:

* **Content hashes, not ETags.** A multipart-upload ETag is not a content hash and changes if identical bytes are
  re-uploaded with another part size. Hash modes are `metadata` (sha256 user-metadata or S3's SHA-256 checksum),
  `compute` (stream + hash), or `etag` (flagged unreliable when multipart; findings are downgraded and say so).
* **Chunk ids/hashes, not counts.** With a chunk-level manifest the engine names exactly which chunks are missing; without
  one it falls back to expected counts and then to gaps in `chunk_index`, and labels that confidence.
* **Graceful with in-flight work.** Documents modified or being processed within `RAGI_GRACE_MINUTES` are `pending`, not
  broken; a job stuck `processing` for hours is flagged.
* **Idempotent ledger.** Issue ids are deterministic, so re-auditing updates rather than duplicates; issues auto-resolve
  when fixed, reopen on regression, and can be ignored with a recorded reason.

## Safe repair workflow

The platform **never blindly deletes vectors** and holds read-only credentials. Repair is a hand-off:

1. detect -> 2. mark stale -> 3. **plan** (smallest safe action per document, with cost estimate vs a full re-embed) ->
4. **trigger** your worker through an HMAC-signed webhook (*reindex phase: add/replace only*) -> 5. worker parses,
chunks, embeds, upserts -> 6. **verify** independently: all expected chunks present, embeddings present, latest version
indexed, metadata correct -> 7. **approve cleanup** (default policy `manual`) -> the removal list is **recomputed from the live
index** and sent to your worker as exact point ids, only for documents that passed verification -> 8. verify again ->
9. everything lands in the audit history.

A worker that reports success but wrote half the chunks is caught by step 6 and its documents keep their old vectors.
See [docs/repair-webhook.md](docs/repair-webhook.md) and the runnable [reference worker](examples/reference_worker/worker.py).

## Feature coverage

| Spec item | Where |
|---|---|
| P0 source-to-index reconciliation, stale / missing / orphan / duplicate / metadata checks | `engine/reconcile.py` |
| P0 document-level integrity report | *Documents* view, `GET /api/report?format=md\|csv\|json`, `ragi report` |
| P0 scheduled audits, alerts, audit history | `RAGI_AUDIT_INTERVAL_MINUTES` or `ragi audit`; Slack-compatible webhook; *Audit history* view |
| P1 pipeline fingerprinting | `Fingerprint` + `RAGI_TARGET_*`; points are classed *fresh / stale / outdated / unknown / orphan* |
| P1 retrieval-level stale-content detection | `engine/retrieval.py`: queries the live index with an affected chunk's vector, tenant-filtered |
| P1 safe reindex recommendations | `engine/planning.py`, *Impact & cost* view, `GET /api/recommendations` |
| P1 repair verification | `repair.py` - five checks per document |
| P1 blast-radius analysis | `engine/blast.py`: open issues, **config change**, or **ingestion-failure window**; query impact from an ingested query log |
| MVP: S3 + Postgres/Supabase + Qdrant, repair webhook, verify | `connectors/`, `repair.py` |
| Explicitly **not** built | embedding model, parser, vector DB, chatbot, full ingestion platform, automatic destructive repair |

## Connect your infrastructure (live mode)

```bash
cp .env.example .env     # then edit; secrets stay in the environment, never in the ledger
RAGI_MODE=live ragi connections     # tests S3, the manifest DB, Qdrant and the ledger, naming whichever is misconfigured
RAGI_MODE=live ragi setup-check    # do S3, the manifest and Qdrant use the same document IDs? (read-only, takes seconds)
RAGI_MODE=live ragi serve
```

Everything is configurable (key patterns, manifest table/columns, Qdrant payload field names): see
[docs/configuration.md](docs/configuration.md). A template manifest schema is in
[`supabase/examples/manifest_example.sql`](supabase/examples/manifest_example.sql).

## Supabase as the control plane

The ledger runs on SQLite locally and on **Supabase Postgres** in production - set `RAGI_DATABASE_URL` and the tables are
created automatically in a private `ragi` schema (or apply
[`supabase/migrations/`](supabase/migrations/20261107000000_ragi_ledger.sql) with `supabase db push`). Setup, pooler
notes and the read-only manifest role: [docs/supabase.md](docs/supabase.md).

## HTTP API

Interactive docs at `/docs` (OpenAPI). Set `RAGI_API_KEY` to require `X-API-Key` / `Authorization: Bearer` on `/api/*`.

| | |
|---|---|
| `GET /api/overview` · `GET /api/connections` | health score, trend, counts · connector status |
| `POST /api/audits` (`{tenant?, documents?, wait?}`) · `GET /api/audits[/{id}]` | start / list audits (async, 409 if one is running) |
| `GET /api/issues` · `GET /api/issues/{id}` · `POST .../ignore` · `POST .../reopen` | the ledger |
| `GET /api/documents` · `GET /api/document?tenant=&document_id=&live=true` | document state; `live` adds a 3-way source/manifest/index view |
| `GET /api/report?format=md\|csv\|json` | document-level integrity report |
| `GET /api/recommendations` · `POST /api/blast-radius` · `POST /api/query-log` | reindex plan + cost, blast radius, query-impact input |
| `POST /api/repairs` · `.../trigger` · `.../verify` · `.../approve-cleanup` · `GET .../payload` | the repair workflow |
| `GET /api/history` | merged audit trail |

## Security model

* **Read-only by construction.** S3: `ListObjectsV2`/`HeadObject` (+`GetObject` only in `compute` mode). Manifest: every
  statement runs in a `READ ONLY` transaction; identifiers are validated before being quoted. Qdrant: `scroll`/`retrieve`/`query`.
* **No document contents are stored.** The ledger holds ids, hashes, versions, counts and evidence. Query logs keep a hash of
  the query text, never the text.
* **Webhooks and alert URLs come from server config, not from API requests** (no SSRF through the API); payloads are
  HMAC-SHA256 signed with a timestamp (replay window 5 min); a real webhook URL without a secret is refused.
* **The web interface is XSS-safe by construction**: every value (document ids are attacker-influenced S3 keys) is inserted as text; strict CSP
  (`script-src 'self'`), `X-Frame-Options: DENY`, `nosniff`.
* **Multi-user app mode** adds: scrypt-hashed passwords, hashed session tokens in `HttpOnly` `SameSite` cookies, an `Origin` check on
  cookie-authenticated writes, database-backed rate limits, per-workspace data isolation (every ledger statement is scoped to a
  workspace), connection secrets encrypted at rest (write-only in the UI), and an SSRF guard that refuses private, loopback and
  cloud-metadata targets for every host a user types in. Details and the honest list of what is *not* covered: [docs/security.md](docs/security.md).
* In the single-user modes, run it behind your own TLS/SSO proxy for anything beyond an internal tool; `RAGI_API_KEY` is a single shared key, not user auth.

## Development

```bash
pip install -e ".[dev]"
ruff check src tests examples api scripts
pytest                                   # the core suite runs anywhere, no services needed (~1 min)
```

The web interface is a React + TypeScript app in [`frontend/`](frontend/). Its **built output is committed** to `src/ragintegrity/api/static/`
(so `pip install`, Docker and Vercel need no Node step). After changing anything in `frontend/`, rebuild and commit the result:

```bash
cd frontend
npm ci
npm run dev        # hot-reload UI on :5173, proxying /api to a backend on :8000 (e.g. `ragi serve --demo`)
npm run typecheck
npm run build      # writes ../src/ragintegrity/api/static (CI fails if the committed build is stale)
```

Some tests need real services and skip themselves unless pointed at them (CI provides all of them):

| Variable | Enables |
|---|---|
| `RAGI_TEST_PG_URL=postgresql://postgres:postgres@localhost:5432/postgres` | the Supabase migrations, the Postgres ledger, the manifest connector, and the end-to-end app-mode tests |
| `RAGI_TEST_QDRANT_URL=http://localhost:6333` (+ `RAGI_TEST_QDRANT_KEY`) | the Qdrant connector against a **real** Qdrant server |
| `RAGI_TEST_S3_ENDPOINT=http://127.0.0.1:5556` | the S3 connector over real HTTP with a custom endpoint (`moto_server -p 5556`, MinIO, ...) |

What the suite proves: the engine finds **exactly** the injected faults (compared to ground truth, in the in-memory demo and through the
real connectors); users can register, sign in, configure and test their own connections and audit them, and **one workspace can never
read or change another's data** (the tests attack this directly); the Supabase migrations apply in order on a real Postgres and stay in
lock-step with the models; the full repair loop - including a worker that lies - works over signed HTTP.

## Known limits (honest list)

* **Scale.** Aggregation is in memory: measured ~19k vectors/s and ~600 B per vector on a laptop (so ~1M vectors ≈ 1 min / 600 MB). For tens of
  millions of vectors, audit per tenant (`ragi audit --tenant X`) or per collection on a schedule. Streaming/sharded reconciliation is the next step.
* `metadata` hash mode costs one `HEAD` per object (parallelised, `RAGI_S3_WORKERS`); at 500k documents prefer
  writing a sha256 into object metadata at upload time, or use S3 inventory-based listing (not built yet).
* A document is expected in **at least one** configured Qdrant collection; per-collection expectations are not modelled.
* The retrieval probe replays an affected chunk's own vector, not real user traffic; it proves searchability and rank, not user impact.
* **Accounts are deliberately minimal**: one user owns one workspace; no email verification or password reset (there is no mail
  provider), no two-factor authentication, no teams or roles. Close sign-up with `RAGI_ALLOW_REGISTRATION=false` once your team has accounts.
* **Serverless audit time limit**: audits on Vercel must finish within ~270 s and say so clearly (which step, how far) when they do not
  (look files up from the manifest instead of listing a huge bucket, audit one tenant at a time, or run `ragi audit`). Only the S3, Postgres and Qdrant integrations exist.
* The "no competitor does this exactly" claim in the product brief is a hypothesis to validate with customer interviews, not something this repo proves.

## License

MIT
