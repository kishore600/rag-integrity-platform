# Edge-case and regression report: features 1, 4 and 2

Built and tested on 2026-11-13 on the branch `claude/features-1-2-4` (a separate working copy, `.claude/worktrees/features-1-2-4`).
**Nothing is committed, pushed or deployed.** Production and `main` are untouched.

## In one paragraph

Three features from the product analysis are built: **Document version integrity (1)**, **Deletion and retrieval verification (4)** and
**Index completeness and scan reliability (2)**. 90 new tests cover the situations below, including 6 end-to-end scenarios on real
services (S3 over HTTP, a real PostgreSQL for the manifest *and* the ledger, a real Qdrant server). The whole suite, 536 tests, passes on real
services (see "Regression"). Writing the tests found **four defects in the existing product**, all fixed, listed below.

## What each feature does now

| # | Feature | What the application now does when the situation arrives |
|---|---|---|
| 1 | Document version integrity | Compares the *revision* the index holds with the source (not only chunk ids): old revision under the right chunk count, old and new chunks side by side under the same ids, a document that got shorter (left-over tail), a changed chunk hash, a changed chunking or embedding configuration, a hash written differently. One table per document (expected against actual) with a verdict. GUIDE.md 3.11. |
| 4 | Deletion and retrieval verification | For a deleted document: is it gone from the source, the manifest and the index, and can a search still return it (up to 3 chunks used as queries)? Verdicts and advice per document, recorded as issues, and the same issue is closed when the cleanup is verified. Works while "Only audit documents found in the source" is on. `POST /api/deletion-check`, `ragi verify-deletions`. GUIDE.md 3.13. |
| 2 | Index completeness and scan reliability | Retries with backoff and honours rate limits; never reports from an incomplete scan; runs end `completed`, `partial`, `failed` (or are `running`); reads the index in slices with a checkpoint after each; resumes from the last checkpoint (`ragi audit --resume`, `POST /api/audits {"resume": true}`); turns a killed run into a resumable partial run; reports points scanned, estimated total, percent, retries, recovered and unrecoverable errors. GUIDE.md 3.12. |

## Defects found in the existing product, and fixed

| # | Defect | How it showed | Fix |
|---|---|---|---|
| 1 | **The retrieval probe filtered by tenant even when the points have none.** | Found by the real-Qdrant deletion test. On an index without a tenant field (your bills layout, the practice lab) every probe returned zero hits, so deleted content that a search *does* return read as "not searchable" and stayed `high`. | The probe filters by tenant only when the point itself has one, using its stored value. The practice lab's orphan vectors are now `critical` (a search finds them at rank 1); its test and workbook were updated to say so. |
| 2 | **A hash spelled differently made every document look stale.** | Designed edge case: `SHA256:ABC…`, `sha256:abc…`, quotes, spaces. | Hashes are compared by value everywhere (source hash in S3, manifest, payload; chunk hashes). |
| 3 | **With "Only audit documents found in the source" on, deleted documents were invisible.** | Designed edge case: the setting ignores everything not in S3, including the leftovers of a deletion. | Documents seen in the source by an earlier audit that are gone now, and documents the manifest marks deleted, are still looked for in the index. Other manifest rows with no file stay ignored. |
| 4 | **A document that got shorter left its old tail active with no alarm when the payloads carry no revision.** | Designed edge case (24 chunks in the index, 20 expected). | New check: chunks the current version does not have are `superseded_active`, with the exact point ids; merged into one issue when old-revision vectors exist too. |

Two mistakes of mine were caught by existing tests and fixed before they could ship: the new chunk-hash check also counted points already known to be
stale (the injected-faults regression test caught it), and a left-over tail also raised a separate chunk-count issue for the same cause.

## Edge cases tested

### Feature 1: versions (23 tests, `tests/test_version_integrity.py`, plus the real-services scenarios)

| Situation | Result |
|---|---|
| The example from the analysis: 24 chunks, count right, all from v2, source is v3 | `stale_embedding`; table shows source version v3/v2 mismatch, count 24/24 match, current-revision chunks 24/0 mismatch; verdict "version mismatch" |
| Healthy document | no findings; every row `match`; verdict `in_sync` |
| New and old chunks under the *same chunk ids* | `superseded_active` naming exactly the old points |
| Re-indexed in place (same point ids overwritten) | healthy |
| Shorter document, payload knows the revision | old tail reported as superseded |
| Shorter document, payload says nothing about the revision (chunk table, or only `expected_chunk_count`) | left-over chunks reported with their ids; exact count produces no finding |
| Old revision plus left-over tail in one document | one issue, not two |
| Payload has no revision but chunk hashes differ from the chunk table | stale, with the hashes as evidence |
| Document hash says current but chunk hashes differ | `metadata_inconsistent` / `chunk_hash_mismatch`, not stale |
| Hash written in 5 spellings (upper case, `sha256:`, `SHA256:`, quoted, `sha-256=`) | treated as equal |
| Chunking configuration changed (all chunks / half way through / mixed inside one document / no target) | `pipeline_drift`, `superseded_active`, or the mixed-settings drift |
| Embedding model version changed | `pipeline_drift`, **high** |
| No hash, no version, no chunk hashes | says "revision cannot be verified" instead of guessing |
| No vectors / source gone | `not_indexed` / `source_missing` |
| Real services: a file changed in S3 and then re-indexed | stale, then resolved at the next audit |
| Real services: shortened document and a changed chunk hash (real Postgres chunk table) | superseded tail and `chunk_hash_mismatch` found |

### Feature 4: deletion and retrieval (22 tests, `tests/test_deletion_verification.py`, plus real-services scenarios)

| Situation | Result |
|---|---|
| Deleted from the source, vectors remain, a search returns them | `deletion_mismatch`, **critical**, evidence table, advice names the vector count |
| Vectors remain but never rank | `deletion_mismatch`, high, "not returned in the top 10 of 3 queries" |
| Clean deletion | `verified_deleted`, no findings |
| Vectors gone, manifest still says indexed | `manifest_not_updated` |
| Cleanup removed only some vectors | mismatch with the real remaining count |
| The search itself fails | reported in the row, never raised; not escalated |
| A named document that still exists | `not_deleted` |
| Same id alive under another tenant | `tenant_mismatch`, critical |
| Vectors in two collections; ids stored as numbers | counted and recognised |
| A document with 40 chunks | 2 or 3 searches, never 40 |
| An audit that ignores other documents (50 manifest rows of another source) | still finds the deleted one; no noise from the 50 |
| Manifest marks a document deleted | checked with no earlier audit; clean ones are counted as verified |
| Vectors of an unrelated document in a shared index | still out of scope (no deletion signal) |
| Whole workflow (service, ledger): audit, delete, audit, verify, cleanup, verify | issue opened, escalated to critical by the search, then closed when the vectors are gone |
| Looking without recording; recording while an audit runs | no trace; refused |
| More candidates than the cap | capped, says how many were left out |
| Over HTTP on the demo world; hosted-app login and rate limit | works; 401 without a session, 429 after 20 |
| Real services: file deleted from real S3, real Qdrant search, cleanup, manifest marked deleted | found, proved searchable at rank 1, `manifest_not_updated`, `verified_deleted`, issue closed |
| Probe on an index with and without a tenant field | no tenant: searches everything; tenant: stays inside it |

### Feature 2: scan reliability (39 tests, `tests/test_scan_reliability.py`, plus real-services scenarios)

| Situation | Result |
|---|---|
| Sliced scan against one pass over the whole index | identical findings, statuses and totals |
| Scan dies in the middle of slice 2 | `partial`: only slice 1's documents are reported; **no document in the unread slices gets any finding or status** (never "missing") |
| Dies before finishing anything | `failed`, nothing recorded |
| One-pass scan dies | reports nothing; says how many points were read and the percentage |
| Resume after a partial run | skips the finished slices, carries the counts over, same totals and health as an uninterrupted audit; ledger identical to a clean audit |
| Resume while the index is still down | stays partial with the same checkpoint |
| Process killed mid-audit (even by something no `except` can catch) | the abandoned run becomes `partial` with its checkpoint and can be resumed |
| A complete audit after a partial one | the partial one becomes history; "resume" with nothing to resume runs a full audit |
| Documents deleted everywhere between the stop and the resume | cleaned up, finished slices untouched; an incomplete audit closes nothing |
| Progress notes | the checkpoint is never dropped by a later note |
| 16 failure types (HTTP 408/425/429/500/502/503/504, timeouts, dropped connections; 400/401/403/404, value errors) | only the ones that can pass are retried |
| Backoff, jitter, cap; `Retry-After`; never past the time budget; a refusal is not retried; retries run out | as designed |
| A misbehaving real cluster (timeouts, a rate limit with `Retry-After`, 502 and 503) | same answer as a healthy one; counters: 4 retries, 2 requests recovered, 1 rate-limited |
| A cluster that never recovers (real Postgres ledger) | partial, resumable, ledger identical to an uninterrupted audit once resumed |

## Benchmark (local Qdrant, 150,000 points, no network; `scripts/benchmark_scan.py`)

| Measurement | Result |
|---|---|
| Plain scroll, page size 100 / 256 / 1,000 (the default) | 9,600 / 16,700 / 45,200 points per second |
| Filtered scroll by document id, no payload index, 10 ids / 5,000 matching points | 0.23 s / 1.0 s |
| Reading | A filtered pass costs about one scan of the collection whatever the number of ids, so slices are thousands of documents. Over a network the rate is set by latency (about 2,500 points per second was measured to your cluster), not by the audit. |

Not benchmarked: a 5-million-point collection (nothing that size is available here). The script measures any real collection read-only, so the number for
the real cluster can be taken with `python scripts/benchmark_scan.py --collection NAME --id-field source_id`.

## Regression

| Run | Result |
|---|---|
| Whole suite, plain checkout (no real services) | **496 passed, 40 skipped** (the skipped ones need real servers) |
| Whole suite with real PostgreSQL, real Qdrant (API key enforced) and S3 over HTTP | **536 passed** |
| Lint (the same scope CI uses) | clean |
| Web interface: typecheck and build | clean; the committed build was regenerated |

Failures met on the way and what they were: two practice-lab tests encoded the old broken probe (fixed, defect 1 above); one test failed because the shared
local Qdrant had been restarted without its API key by another session, so a second, key-enforcing Qdrant was started and the suite rerun; the
in-memory Postgres test server crashed once under load and was restarted. None was left unexplained.

## What is not done, and decisions for the owner

1. **Not committed, pushed or deployed.** Review `git diff` on the branch `claude/features-1-2-4`; ship by committing, merging and pushing as before.
2. **Feature 3 (out-of-order retries) was not built**, as requested. Its *result* (an old revision active again) is already caught by `stale_embedding`
   and `superseded_active`; job timelines would need job data from the customer's pipeline.
3. **No new screens.** The interface got the minimum so the new run state does not break it (a "Partial" badge, filter and notice, and the types). The
   version table, the deletion check and a "Resume" button have API support only: the UI session can build them from GUIDE.md 3.11 to 3.13.
   `docs/user-guide` was not updated.
4. **Behaviour changes on your live data after a deploy:** (a) orphan vectors confirmed by a real search become `critical` instead of `high`
   (the probe now works on indexes without a tenant field); (b) deleted documents are checked even with "Only audit documents found in the source" on;
   (c) hash spelling no longer causes false stale findings; (d) documents with a chunk table can show the new left-over and chunk-hash findings.
   With your 2,857 source documents the audit is one slice (slices are 5,000 documents), so the run itself behaves as today.
5. **No database migration is needed.** The new run status and trigger fit the existing columns. The only new setting, `RAGI_AUDIT_SLICE_DOCUMENTS`
   (default 5000), is optional.
6. **Limits, stated plainly:** a scan of the whole index (the setting off) is one pass and cannot resume; resume works in slices; the isolation picture is
   left to the next full audit after a resumed one; the retrieval test uses the stored vectors of up to 3 chunks, so it proves searchability, not user traffic;
   not tested against your real systems.
7. **The Slack alert could not be sent.** No Slack connector was available in this session. The message is below, and a desktop/phone notification was sent instead.

## Slack message (ready to paste)

> RAGGuard: features 1, 4 and 2 are built and tested, not deployed. Version integrity, deletion and retrieval verification, and reliable large-index scans
> (retries, partial runs, resume). 90 new tests incl. 6 end to end on real S3, Postgres and Qdrant; whole suite 536/536 passing on real services.
> Found and fixed 4 defects in the existing product, including a retrieval probe that never worked on indexes without a tenant field.
> Branch `claude/features-1-2-4`. Report: `docs/edge-case-report-features-1-2-4.md`. Say "Publish" to ship.
