# Architecture

```
src/ragintegrity/
  models.py            dataclasses: SourceDoc, ManifestRow, IndexedChunk, Fingerprint, Finding, DocSummary, Scope
  config.py            RAGI_* settings (pydantic-settings), identifier validation
  connectors/          READ-ONLY views: s3.py · postgres.py · qdrant.py · payload.py · factory.py
  engine/
    index_state.py     streaming aggregation: classify each vector the moment it is scanned
    reconcile.py       pure function: (source, manifest, chunk manifest, index) -> findings + per-document summaries
    retrieval.py       probes: can the bad content actually be retrieved?
    planning.py        repair items + cost / workload estimate
    blast.py           blast radius for open issues / config change / ingestion failure
    audit.py           pulls the three inventories and runs the above
  ledger.py            SQLAlchemy store: SQLite locally, Postgres (Supabase) in prod
  service.py           the one object API/CLI/scheduler use: audits, locking, overview, inspection
  repair.py            plan -> signed webhook -> verify -> approved cleanup -> verify
  alerts.py report.py  Slack-compatible alerts · markdown/CSV/JSON report
  api/                 FastAPI app; static/ holds the BUILT web interface (committed, so deploys need no Node step)
  demo/                synthetic world with injected faults, toy pipeline, seeding for live infrastructure
frontend/                    the web interface source (React + TypeScript + Vite + Tailwind); `npm run build` writes api/static/
examples/reference_worker/   the customer-side receiver of the repair webhook
supabase/migrations/         ledger schema (kept in sync with ledger.py by a test)
```

## The reconciliation model

Three inventories, keyed by `(tenant_id, document_id)`:

* **source** - what exists now (S3 key, content hash, version, size, modified time)
* **manifest** - what the pipeline *believes* it did (status, hashes, expected/indexed counts, fingerprint, ACL hash)
* **index** - what is actually searchable (Qdrant payloads, optionally vector sanity)

The index is scanned **after** the source inventory is loaded, and each point is classified immediately and folded into a
compact per-document state, so memory is proportional to the corpus, not to scan buffers:

| class | meaning |
|---|---|
| `fresh` | hash/version matches the live source **and** the pipeline fingerprint matches the target |
| `stale` | hash/version differs: an older version of the document |
| `outdated` | content is current but built with a different parser/chunker/embedding config |
| `unknown` | payload carries no hash/version: freshness is inferred from the manifest instead |
| `orphan` | the document no longer exists at the source |

The decision table per document:

| source | index | result |
|---|---|---|
| gone | vectors, doc exists under another tenant | `tenant_mismatch` |
| gone | vectors | `orphan_vector` |
| gone | none, manifest row | `manifest_orphan` |
| present | none | `missing_embedding` (critical if the manifest claims success) |
| present | only stale | `stale_embedding` |
| present | fresh + stale/outdated | `superseded_active` |
| present | only outdated | `pipeline_drift` |
| present | fresh | completeness (`partial_index`), `duplicate_chunk`, `empty_embedding`, `metadata_inconsistent` |

Collection-level checks (full runs only): vectors without a document id, and target embedding dimension vs the collection's vector size.

## Issue lifecycle

Issue id = hash(type, tenant, document, collection), so the same problem is the *same row* across audits.
`open -> resolved` when a run that covers the document no longer finds it; `resolved -> open` (reopened) on regression;
`ignored` is sticky and carries a reason. Every change is an `issue_events` row; with `audit_runs` and `repair_events`
that is the audit history. Scoped runs (verification) only ever resolve issues inside their scope.

## Repair state machine

```
draft --trigger--> triggered --verify--> completed
                                  |----> cleanup_pending --approve-cleanup--> cleanup_triggered --verify--> completed
                                  |----> partial / failed --re-trigger failed docs--> triggered
```

Per-document statuses: `planned -> reindexed | awaiting_cleanup | completed | failed`, each with the five verification checks.

## Concurrency

One audit at a time per process (`threading.Lock`); a second request gets HTTP 409. API-started audits run in a background
thread and are polled by run id. Run one app instance per ledger, or add a Postgres advisory lock before scaling out.
