# Reference: every value

This chapter is a set of lookup tables. Use it when you see a word, a badge, a colour, a status or a number in RAGGuard and want to know exactly what it means and what to do about it. It covers the issue types, severities, statuses, document states, vector classes, audit runs and their numbers, the health score, repair plans, connection states, test results, alert outcomes, settings, the HTTP API, limits, and a glossary. The explanations of whole pages are in the other chapters; this one is for looking things up. New to the vocabulary? Start with [Concepts you need](02-concepts.md).

Colours below are the ones the interface uses. **Green** means good, **amber** means look at it, **red** means act, **blue** means in progress or informational, **grey** means neutral.

**On this page**

- [Issue types](#issue-types)
- [Issue titles in the list](#issue-titles-in-the-list)
- [Metadata problems](#metadata-problems)
- [Collection-level findings](#collection-level-findings)
- [Repair actions](#repair-actions)
- [Severities and badge colours](#severities-and-badge-colours)
- [Issue statuses](#issue-statuses)
- [Issue event names](#issue-event-names)
- [Document statuses](#document-statuses)
- [Document states](#document-states)
- [Vector classes](#vector-classes)
- [Audit runs: kinds, statuses and triggers](#audit-runs-kinds-statuses-and-triggers)
- [Audit stats fields](#audit-stats-fields)
- [Change counters](#change-counters)
- [Health score](#health-score)
- [Repair plans](#repair-plans)
- [Connection states](#connection-states)
- [Test check statuses](#test-check-statuses)
- [Alert delivery outcomes](#alert-delivery-outcomes)
- [Manifest status values](#manifest-status-values)
- [Settings groups and fields](#settings-groups-and-fields)
- [API roles and endpoints](#api-roles-and-endpoints)
- [Limits and rate limits](#limits-and-rate-limits)
- [Glossary](#glossary)
- [Related chapters](#related-chapters)

## Issue types

There are eleven issue types. The label is what you see in the interface; the internal name is what appears in the API, in exports and in the **Type** filter's address.

| Label | Internal name | Severity and how it is decided | Systems involved | Recommended action | What it means and what to do |
|---|---|---|---|---|---|
| Missing embeddings | `missing_embedding` | High. Critical when the manifest claims success (a success-like status, or an indexed chunk count above 0). Not raised while the document is inside the grace period. | Amazon S3, Qdrant | Full reindex | The document exists in S3 but the index holds nothing for it, so users get no answer from it. Re-process the document. If the pipeline reported success, find out why it wrote nothing. |
| Partial index | `partial_index` | High. Critical when the manifest claims success. Medium when only gaps in the chunk numbers suggest it ("suspected"). Skipped when the document is stale. | Qdrant, PostgreSQL | Re-embed missing chunks | Only some of the expected chunks are indexed, so answers can be silently incomplete. Expected chunks come from the chunk table if you configured one, otherwise from the manifest's expected chunk count, otherwise from gaps in the chunk numbers. Re-embed the missing chunks (a full rebuild is also safe). |
| Stale document version | `stale_embedding` | High. Medium when the source hash is a multipart ETag, which is not a real content hash. Not raised during the grace period. | Amazon S3, Qdrant | Full reindex | The source changed but every indexed vector still describes the previous version. Also raised when the vectors carry no hash or version and the manifest's hash differs from the source's. Re-process the document. |
| Superseded vectors active | `superseded_active` | Medium. High when a retrieval probe shows the old content is really returned. | Qdrant | Remove old vectors | The current version is indexed, but vectors of an older version or built with an older pipeline setup still answer queries and can outrank the new content. Remove them after the replacements are verified. |
| Orphan vectors | `orphan_vector` | High. Critical when a retrieval probe shows the content is returned for a matching query. | Amazon S3, Qdrant | Remove old vectors | The document was deleted at the source but its vectors are still searchable. It exists under no other tenant. Remove the vectors. |
| Duplicate chunks | `duplicate_chunk` | Medium | Qdrant | Remove old vectors | The same chunk is indexed more than once, typically after retried jobs. The first copy seen is kept and the rest are listed for removal. |
| Metadata mismatch | `metadata_inconsistent` | The highest severity among its problems (see [Metadata problems](#metadata-problems)) | PostgreSQL, Qdrant | Fix metadata. Needs a human for the collection-level variant. | The source, the manifest and the vector payloads disagree on counts, versions, access-control hashes or required fields. One issue per document lists all its problems. Correct the manifest or the payload; no re-embedding is needed. |
| Pipeline drift | `pipeline_drift` | High when the embedding model, its version or the embedding dimensions differ. Medium when only the parser, chunking version, chunk size, chunk overlap or preprocessing differ. Critical for the collection-level size mismatch. | PostgreSQL, Qdrant | Full reindex. Needs a human for the collection-level variant. | Vectors were built with a different setup than your target pipeline (or the vectors of one document disagree among themselves). Mixed embedding spaces degrade retrieval in ways that are hard to see. Re-process the document with the target pipeline. |
| Empty embeddings | `empty_embedding` | High | Qdrant | Full reindex | Points exist whose vector is missing, empty or all zeros, so they can never match a query. Only checked when **Detect empty embeddings** is switched on for the Qdrant connection. |
| Tenant mismatch | `tenant_mismatch` | Critical | Qdrant | Remove old vectors | Vectors are tagged with a tenant under which the document does not exist, while it does exist under another. A cross-customer leak risk. Treat it as a security incident. |
| Orphan manifest row | `manifest_orphan` | Low | PostgreSQL | Needs a human | The manifest lists a document that is gone from both the source and the index, and its status is not "deleted", "tombstoned" or "removed". Harmless to users, but it clutters your records. Retire the row in your pipeline. |

## Issue titles in the list

The **Issue** column shows a short title. This table maps each title to its type.

| Title | Type |
|---|---|
| Document has no embeddings in the index (the text " (pipeline claims success)" is added when the manifest claims success) | Missing embeddings |
| Only part of the document is indexed (with the same optional text) | Partial index |
| Embeddings are from an older version of the document | Stale document version |
| Superseded vectors are still active next to the current ones | Superseded vectors active |
| Vectors remain for a document that no longer exists | Orphan vectors |
| Duplicate active chunks | Duplicate chunks |
| Metadata disagrees between systems | Metadata mismatch |
| Vectors without a document id | Metadata mismatch, collection level |
| Indexed with an outdated pipeline configuration | Pipeline drift |
| Chunks of one document were built with different pipeline configs | Pipeline drift |
| Collection vector size does not match the target embedding model | Pipeline drift, collection level |
| Points exist without a usable embedding | Empty embeddings |
| Vectors are tagged with the wrong tenant | Tenant mismatch |
| Manifest row for a document that no longer exists | Orphan manifest row |

## Metadata problems

A **Metadata mismatch** issue lists one or more of these problems under **Problems found** in its evidence.

| Code | Severity | Meaning |
|---|---|---|
| `missing_payload_fields` | Medium | Vector payloads lack fields you require (by default `document_id`, `source_hash`, and `tenant_id` once there is more than one tenant) |
| `untracked_in_manifest` | Medium | Vectors exist for a current document but the manifest has no row for it |
| `manifest_count_mismatch` | Medium | The manifest says N chunks are indexed and the index holds a different number. Hidden when a partial index already explains it. |
| `acl_mismatch` | High | Vectors carry a different access-control hash than the manifest, so permissions may be wrong at query time |
| `manifest_lags_index` | Low | The index is current but the manifest still records an older source hash |
| `manifest_version_mismatch` | Low | The manifest's indexed version differs from the source version although the content hashes agree |
| `status_failed_but_indexed` | Low | The manifest status says failed although the document is indexed |
| `unattributed_vectors` | High | Collection level: points that carry no document id. See below. |

## Collection-level findings

Two findings belong to a whole Qdrant collection, not to one document. In lists the document column reads "Whole collection" (or "Whole tenant" in some run lists). They cannot become repair plans. Fix them in your own systems, then audit again.

| Finding | Type | Severity | Meaning |
|---|---|---|---|
| Vectors without a document id | Metadata mismatch | High | N points in a collection carry no document id, so they cannot be matched to any document |
| Collection vector size does not match the target embedding model | Pipeline drift | Critical | The vector size of a collection differs from **Embedding dimensions** in **Settings**, **Pipeline**, so queries embedded with the target model cannot match it |

## Repair actions

| Internal name | Label shown | What it means |
|---|---|---|
| `reindex_full` | Full reindex | Re-process the whole document from the latest source: parse, chunk, embed and write, then update the manifest |
| `reindex_chunks` | Re-embed missing chunks | Re-embed only the missing chunks (a full rebuild is also safe) |
| `cleanup_vectors` | Remove old vectors | Remove the listed vectors, only after the replacements are verified and an operator approves |
| `fix_metadata` | Fix metadata | Correct the manifest or the payload; no re-embedding |
| `investigate` | Needs a human | No automatic repair exists; someone has to look |

How a repair plan chooses actions for one document:

- Missing, stale, drifted or empty-embedding issues give **Full reindex**.
- Otherwise, a partial index gives **Re-embed missing chunks**.
- A metadata mismatch adds **Fix metadata** only when there is no **Full reindex** (a full reindex already rewrites the manifest).
- Superseded, duplicate, orphan and tenant-mismatch issues set the "remove old vectors" flag, which becomes **Remove old vectors** after verification.
- An orphan manifest row and any collection-level finding give no automatic action (**Needs a human**).

## Severities and badge colours

| Severity | Badge colour | Rank | Notes |
|---|---|---|---|
| Critical | Red | 4 | Act now |
| High | Amber | 3 | Fix soon |
| Medium | Blue | 2 | Plan to fix |
| Low | Grey | 1 | Housekeeping |
| Info | Grey | 0 | Exists in the data model, but none of the current checks raises it |

The severity chips on the **Issues** tab show the four levels from critical to low, with the number of open issues of each. The colour tones used for badges everywhere are: green (good, completed), amber (warning, look at it), red (critical, failed), blue (information, in progress) and grey (neutral).

## Issue statuses

| Status | Badge | Meaning | How it changes |
|---|---|---|---|
| Open | Amber | The audit found it and it has not been fixed or ignored | Becomes Resolved when an audit that covers the document no longer finds it. Becomes Ignored when you ignore it. |
| Resolved | Green | An audit no longer finds it | Becomes Open again (its "Reopened" count goes up) if a later audit finds it again |
| Ignored | Grey | You decided to accept it and, optionally, said why | Stays Ignored, even if later audits still find it, until you click **Reopen** |

An issue keeps one identity across audits: the same problem on the same document is the same row, and its **Seen** number counts the audits that saw it. A scoped audit only resolves issues inside its own scope.

## Issue event names

Each issue has a timeline of events.

| Event | Issue timeline text | Activity log label | When it is recorded |
|---|---|---|---|
| `opened` | Detected by an audit | Issue opened | The first time an audit finds the problem |
| `reopened` | Came back after it was resolved | Issue reopened | An audit finds a problem that was Resolved |
| `resolved` | Resolved: the index now matches the source | Issue resolved | An audit that covers the document no longer finds it |
| `severity_changed` | Severity changed from X to Y | Severity changed | An audit finds an open issue at a different severity (higher or lower) |
| `ignored` | Ignored, with "Reason: ..." when you gave one | Issue ignored | You click **Ignore** |
| `unignored` | Reopened by a user | Issue unignored | You click **Reopen** (on an Ignored or a Resolved issue) |

The Activity log can also show the label "Issue escalated". The product records an escalation as `severity_changed`, and counts it as Escalated in the [change counters](#change-counters).

## Document statuses

The audit gives every document one of five statuses. They are shown under **Document status** on Overview, in the **Status** filter on Documents, and as the tabs of the Reconciliation documents table.

| Status | Colour (Overview bar) | Meaning | How it is decided |
|---|---|---|---|
| Healthy | Green | Source, manifest and index agree | No findings |
| Degraded | Amber | Searchable, with minor issues | The worst finding is medium or low |
| Broken | Red | Serious issues found | At least one critical or high finding |
| Pending | Blue | Still being processed | Changed or in flight within the grace period and no findings. Not judged yet. |
| Orphaned | Grey | Deleted at the source, vectors remain | Not in the source, but vectors exist |

"Needs attention" on Documents and Reconciliation means Degraded plus Broken. A document's status comes from what the audit finds, not from your Ignore decisions.

## Document states

The **Embedding status** column on Documents (and the **Status** column in the Reconciliation documents table) is a simpler label derived from the status and the issue types, checked in this order.

| State | Colour | How it is derived |
|---|---|---|
| Processing | Blue | The document status is Pending |
| Missing embeddings | Red | The document has a Missing embeddings issue |
| Stale | Amber | The document has a Stale document version issue, or its status is Degraded |
| Healthy | Green | The status is Healthy |
| Failed | Red | The status is Broken or Orphaned (and neither of the two rules above applied) |

"Failed" does not mean a pipeline job failed. It means the audit found serious problems with the document, or that the document is an orphan. A Broken document with only, for example, a tenant mismatch shows as Failed.

## Vector classes

While the index is scanned, RAGGuard gives every vector one class by comparing it with the live source and your target pipeline. You see the classes on the **Chunks** tab of a document after **Inspect live**.

| Class | Colour | Meaning | How it is decided |
|---|---|---|---|
| Fresh | Green | Matches the current source and the pipeline | Its hash (or, if it has none, its version) matches the source, and it does not conflict with the target pipeline |
| Stale | Amber | Built from an older version of the document | Its hash (or version) differs from the source's |
| Outdated | Amber | Current content, built with an older pipeline setup | Hash matches, but a value it records conflicts with the target pipeline |
| Unknown | Grey | The index does not say which version it is | The payload carries no hash and no version, so freshness cannot be established |
| Orphan | Red | The document no longer exists at the source | The document is not in the source |

Fresh and Unknown vectors count as live. The checks run in this order: Orphan, then Stale, then Outdated, then Fresh or Unknown.

## Audit runs: kinds, statuses and triggers

These are the **Type**, **Status** and **Trigger** values in **Audit history**.

| Type | Meaning |
|---|---|
| Full | The whole corpus. Only full completed audits feed the **Health over time** chart and the three-way comparison on Reconciliation. |
| Scoped | One tenant (**Scoped audit**), or specific documents (**Re-audit document**, or the API's `documents` list) |
| Verify | A scoped audit run by a repair plan, to check its documents (**Verify now**) or to prepare the removal list (**Approve cleanup**) |

| Status | Badge | Meaning |
|---|---|---|
| Running | Blue | Started and not yet finished |
| Completed | Green | Finished and recorded |
| Failed | Red | Stopped with an error, shown on the run's page. A run that was cut off (for example a hosting function that was killed) is marked Failed with "abandoned: the process running it stopped", plus the last step it reached. |

| Trigger | What started it |
|---|---|
| Api | A request to the HTTP API. This includes the **Run audit**, **Run full audit**, **Scoped audit** and **Re-audit document** buttons of the web interface (which use the API), and calls made with an API key. You cannot tell the two apart by this value. |
| Repair verify | **Verify now** on a repair plan (or your worker's callback) |
| Cleanup prep | **Approve cleanup**, which first audits the plan's documents again to get the exact list of vectors to remove |
| Cli | The `ragi audit` command |
| Schedule | The built-in scheduler of a single-user server (not available in the hosted app) |
| Bootstrap | The first audit that the demo server runs by itself |
| Manual | The default name when code starts an audit without giving a trigger. You will rarely see it. |

The **Scope** column reads **All**, a tenant name, or "N documents".

## Audit stats fields

Every finished run records these numbers. Some appear only when they apply. The run page shows the tiles **Documents**, **Source documents**, **Manifest rows**, **Index vectors**, **Retrieval probes** and **Health score**.

| Field | Meaning | Shown as |
|---|---|---|
| `source_documents` | Documents found in S3 (after the key prefix and key pattern) | **Source documents** ("in Amazon S3"), and **Source documents** on Reconciliation |
| `manifest_rows` | Rows read from the manifest (when **Only audit documents found in the source (S3)** is on, only rows for documents found in S3) | **Manifest rows** ("in PostgreSQL") |
| `index_points` | Vectors read from Qdrant in this audit, including orphans and vectors with no document id | **Index vectors** ("in Qdrant") |
| `documents_total` | Documents compared in total (the union of what the three systems hold, within the scope) | **Documents** ("compared in total") |
| `documents_by_status` | Documents per status (Healthy, Degraded, Broken, Pending, Orphaned) | API only |
| `findings_total` | Number of findings (issues found) | **Findings**; the **Issues** column of the runs table |
| `findings_by_severity` | Findings per severity | **By severity** |
| `findings_by_type` | Findings per type | **By type** |
| `health_score` | (Healthy + Pending documents) divided by all documents, as a percentage. 100 when there are no documents. | **Health score**; the **Health** column |
| `retrieval_probes` | How many probe searches were sent to the index. Present only when probes are on and the audit found something. | **Retrieval probes** ("queries sent to the index") |
| `diff` | The [change counters](#change-counters) | **Changes in this audit**; the **Changes** column |
| `scope` | The tenant or number of documents audited, empty for a full audit | **Scope** |
| `duration_seconds` | How long the audit took | **Duration** |
| `alerts` | What happened to the alert: `sent` (0 or 1), `issues`, `reason`, `error` | **Alert delivery** card; **Recent deliveries** |
| `required_payload_fields` | The fields every vector had to carry in this audit | API only |
| `source_documents_only` | True when the "only audit documents found in the source" switch was on | API only |
| `isolation` | The tenant isolation picture (overall result, tenants and five checks), including how many leaks were searched live (`leaks_tested_by_search`) and how many a search returned (`leaks_confirmed_reachable`). Recorded only by full audits. | The [Isolation](20-isolation.md) page |
| `progress` | While running, the current step and seconds elapsed. The steps are "listing the source documents (S3)", "reading the processing manifest", "looking up the files the manifest names (S3)", "reading the vector index (Qdrant)" and "comparing the three lists". | Shown in the failure message of an abandoned run |

## Change counters

These five numbers describe what an audit changed compared with the audit before it. You see them as **Since the previous audit** on Reconciliation, as **Last audit** on Overview and as **Changes in this audit** on the run page. In the runs table the **Changes** column shows "N opened" and "N resolved".

| Counter | Meaning | Colour when above zero |
|---|---|---|
| Opened | New issues, found for the first time | Amber |
| Reopened | Issues that had been Resolved and came back | Amber |
| Escalated | Open issues whose severity went up | Amber |
| Resolved | Open issues that this audit no longer found | Green |
| Unchanged | Open issues seen again. An issue that is also counted as Escalated is counted here too. | Default |

Ignored issues that are seen again appear in none of the counters.

## Health score

**Health score** is the share of documents that are healthy, as a percentage: (Healthy documents + Pending documents) divided by all documents, rounded to one decimal place. Pending documents count as healthy because they are probably still being ingested.

| Score | Badge colour |
|---|---|
| 90% and above | Green |
| 70% up to just under 90% | Amber |
| Below 70% | Red |
| No score yet | Grey, with a dash |

Where it appears: the first card on Overview (from the latest state of all documents, so a scoped or verification audit that refreshes some documents can move it), the **Health over time** chart (one point per completed full audit), the **Health** column in Audit history, the run page, Tenant health (per tenant) and the Reconciliation comparison. A scoped audit's own score covers only its scope. The score is never changed by ignoring an issue.

## Repair plans

### Plan statuses

| Status | Badge | Meaning | Buttons you get |
|---|---|---|---|
| Draft | Grey | Created, nothing sent. | **Trigger repair** |
| Triggered | Blue | The repair request was sent to your worker | **Verify now** |
| Partial | Amber | Some documents are fixed and some are not | **Send repair again**, **Verify now** |
| Failed | Red | The index still has the problems | **Send repair again**, **Verify now** |
| Cleanup pending | Amber | Replacements are verified, removal of old vectors needs your approval | **Approve cleanup** |
| Cleanup triggered | Blue | The removal request was sent to your worker | **Verify now** |
| Completed | Green | Every repair is verified | none |

**View payload** is available in every status. In the API, **Approve cleanup** is also accepted for a Partial plan (it then covers only the documents that already passed).

How **Verify now** decides the plan status: when every document is Completed, the plan is Completed. When every document is Completed, Replacements verified or Waiting for cleanup (and at least one is not Completed), the plan is Cleanup pending. When some documents are Not fixed yet and the others are in any other status, the plan is Partial. When every document is Not fixed yet, the plan is Failed.

### Item statuses

| Item status | Label shown | Colour | Meaning |
|---|---|---|---|
| `planned` | Planned | Grey | Not yet checked |
| `reindexed` | Replacements verified | Amber | The new vectors are in place; old ones await cleanup |
| `awaiting_cleanup` | Waiting for cleanup | Amber | The document needs only removal of vectors and is ready for it |
| `completed` | Completed | Green | All five checks pass |
| `failed` | Not fixed yet | Red | At least one of the first four checks fails. The line "Still found: ..." names what remains. |

### Verification checks

After a repair, a scoped audit of the plan's documents runs, and each document gets these five checks.

| Label | Internal name | Passes when the verification audit finds none of |
|---|---|---|
| All chunks present | `expected_chunks_present` | Missing embeddings, Partial index |
| Embeddings present | `embeddings_present` | Empty embeddings, Missing embeddings |
| Latest version indexed | `latest_version_indexed` | Stale document version |
| Metadata correct | `metadata_correct` | Metadata mismatch, Pipeline drift |
| Old vectors removed | `old_vectors_inactive` | Superseded vectors active, Duplicate chunks, Orphan vectors, Tenant mismatch |

A document is Completed when all five pass. It is Replacements verified (or Waiting for cleanup) when the first four pass and the fifth does not. Otherwise it is Not fixed yet.

### Plan events

| Event | Title in the plan's History | Label in the Activity log |
|---|---|---|
| `created` | Plan created | Repair plan created |
| `reindex_triggered` | Repair sent to your worker | Re-index requested |
| `worker_callback` | Your worker reported back | Worker callback received |
| `verified` | One of: "Verified: every repair is in place"; "Verified: replacements are in place, old vectors await approval"; "Verified: some documents still have issues"; "Verified: the repairs are not in place yet" | Repair verified |
| `cleanup_triggered` | Cleanup sent to your worker | Vector cleanup requested |

## Connection states

| State | Badge | Where | Meaning |
|---|---|---|---|
| Connected | Green | Data sources cards, Integrations | Configured, and the live check passed |
| Error | Red | Data sources cards | Configured, but the live check failed. The card's line shows the error. |
| Not connected | Grey | Data sources cards | Not configured yet |
| Checking | Blue | Data sources cards | The live check is running |
| Status unavailable | Amber | Data sources cards | Configured, but the live status could not be read just now |
| Configured / Not configured | Green / Grey | Repair webhook card | Whether the repair webhook has any saved value |

On **Overview**, **Connection health** shows a green dot for a system that answers and a red dot for one that does not, with the response time in milliseconds. A system counts as configured only when its required fields are present: the S3 bucket and both access keys, the manifest connection string, and the Qdrant URL.

## Test check statuses

**Test connection** (and **Test** on a card) returns one line per check. The overall verdict is **Test failed** if any check is red, **Test passed with warnings** if any is amber, and **Test passed** otherwise. **Check settings** (repair webhook, alerts) only validates values and shows one line.

| Check status | Icon | Meaning |
|---|---|---|
| ok | Green tick | The check passed |
| warn | Amber triangle | It works, but something will limit the audit. Read it. |
| fail | Red cross | It does not work. The message says what to change. |

| System | Checks, in order |
|---|---|
| Amazon S3 | Bucket reachable, Documents found (only when empty), Key pattern, Object metadata (only on failure), Content hashes |
| PostgreSQL | Database reachable, Manifest table, Columns used for checks (only when columns are missing), Rows, Role is read-only, Chunk manifest |
| Qdrant | Qdrant reachable, Collections, Collection NAME and Payload of NAME (for up to the first five collections) |
| Anything | Configuration (a problem with a required field or a setting), Connection (an unexpected error) |

## Alert delivery outcomes

On **Alerts**, **Recent deliveries** lists what happened after each of the latest 50 audits.

| Outcome | Badge | Detail text | Meaning |
|---|---|---|---|
| Delivered | Green | "Sent to the alert webhook." | One message was sent and the webhook accepted it |
| Failed | Red | The error, for example the name of an HTTP error | A message was due but the webhook did not accept it (one attempt, 10-second wait, no retry). The audit itself is not affected. |
| Not sent | Grey | "No alert webhook was configured." or "No new issues at or above the minimum severity." | Nothing was due, or nowhere to send it |

The **Show** filter offers "Delivered or failed" (the default), "Every audit", "Delivered", "Failed" and "Not sent". An alert is due only for issues that are new, reopened or escalated, and at or above the **Minimum severity**.

## Manifest status values

RAGGuard reads the manifest's `processing_status` column (or whichever column you map to it). Matching ignores capital letters and spaces at the ends. Any other value is treated as unknown: neither success, nor in flight, nor failed.

| Group | Values it recognises | Effect |
|---|---|---|
| Success | `success`, `succeeded`, `indexed`, `completed`, `complete`, `done`, `ready`, `ok`, `processed`, `true` | The pipeline "claims success". A document with no vectors then gets **Critical** instead of High. (`true` lets you map a true/false column such as `is_indexed`.) An indexed chunk count above 0 also counts as claiming success for a missing document. |
| In flight | `pending`, `queued`, `processing`, `running`, `in_progress`, `indexing`, `parsing`, `embedding` | A document in one of these states that was updated within the grace period is **Pending**, not broken. A document stuck in one of them for longer is flagged, and the issue text says since when. |
| Failed | `failed`, `error`, `errored`, `failure` | Explains a missing document ("marked ... and never retried successfully"). A document that is indexed although the manifest says failed gets the low problem `status_failed_but_indexed`. |
| Deleted | `deleted`, `tombstoned`, `removed` | A manifest row with one of these for a document that is gone does **not** raise an Orphan manifest row issue |

## Settings groups and fields

There are seven settings groups. The detailed fields, help and examples are in the chapters linked in the first column. Secret fields are encrypted when stored, are write-only (after saving, the form says "A value is saved" and never shows the value), and can be left empty to keep the stored value. Optional text fields that you leave empty use the default. Text fields have length limits (for example 255 characters for Bucket and 4,000 for the JSON fields), and a message tells you when you exceed one.

Every address you enter (S3 endpoint, Qdrant URL, database host, repair webhook, alert webhook) must be a public one in hosted mode.

### Source documents (S3)

Where: **Data sources**, Amazon S3 card, **Configure** or **Edit**. Detail: [Data sources](04-data-sources.md).

| Label | Internal key | Type | Required | Secret | Default |
|---|---|---|---|---|---|
| Bucket | `bucket` | text | Yes | No | none |
| Key prefix | `prefix` | text | No | No | empty (whole bucket) |
| Region | `region` | text | No | No | none |
| Custom endpoint | `endpoint_url` | address | No | No | none (AWS) |
| Access key ID | `access_key_id` | text | Yes | Yes | none |
| Secret access key | `secret_access_key` | text | Yes | Yes | none |
| Content hash | `hash_mode` | `metadata`, `compute`, `etag` | No | No | `metadata` |
| SHA-256 metadata key | `sha256_metadata_key` | text | No | No | `sha256` |
| Key pattern (regex) | `key_pattern` | pattern with a `(?P<document_id>...)` group | No | No | `^(?P<tenant_id>[^/]+)/(?P<document_id>.+)$` |
| Default tenant | `default_tenant` | text | No | No | `default` (used when the key pattern has no tenant group) |
| Look up files from the manifest (skip listing the bucket) | `lookup_from_manifest` | switch | No | No | off |

### Processing manifest (PostgreSQL / Supabase)

Where: **Data sources**, PostgreSQL card. Detail: [Data sources](04-data-sources.md).

| Label | Internal key | Type | Required | Secret | Default |
|---|---|---|---|---|---|
| Connection string | `database_url` | `postgresql://...` | Yes | Yes | none |
| Schema | `schema` | identifier (letters, digits, underscores) | No | No | `public` |
| Document table | `table` | identifier | No | No | `rag_document_manifest` |
| Chunk table (optional) | `chunk_table` | identifier | No | No | none |
| Column map (JSON) | `column_map` | JSON object of text values | No | No | empty |
| Chunk column map (JSON) | `chunk_column_map` | JSON object of text values | No | No | empty |

The manifest columns RAGGuard knows are: `tenant_id`, `document_id` (the only mandatory one), `source_uri`, `source_version`, `source_hash`, `parsed_hash`, `parser_version`, `chunking_version`, `chunk_size`, `chunk_overlap`, `embedding_model`, `embedding_model_version`, `embedding_dim`, `preprocessing`, `expected_chunk_count`, `indexed_chunk_count`, `indexed_version`, `processing_status`, `last_verified_at`, `updated_at`, `acl_hash` (21 in all). The chunk table columns are `tenant_id`, `document_id` (required), `chunk_id` (required), `chunk_index`, `chunk_hash`.

### Vector index (Qdrant)

Where: **Data sources**, Qdrant card. Detail: [Data sources](04-data-sources.md).

| Label | Internal key | Type | Required | Secret | Default |
|---|---|---|---|---|---|
| URL | `url` | address | Yes | No | none |
| API key | `api_key` | text | No | Yes | none |
| Collections | `collections` | comma-separated names | No | No | empty (every collection) |
| Payload field map (JSON) | `payload_map` | JSON object of text values; dotted paths reach nested fields | No | No | empty |
| Named vector | `vector_name` | text | No | No | none |
| Detect empty embeddings | `check_vectors` | switch | No | No | off |

The payload fields RAGGuard reads are `tenant_id`, `document_id`, `chunk_id`, `chunk_index`, `chunk_hash`, `source_hash`, `source_version`, `parser_version`, `chunking_version`, `chunk_size`, `chunk_overlap`, `embedding_model`, `embedding_model_version`, `embedding_dim`, `preprocessing` and `acl_hash`.

### Target pipeline

Where: **Settings**, **Pipeline** tab, card "Expected pipeline". All fields are optional and empty by default. Detail: [Settings](14-settings.md).

| Label | Internal key | Type and range |
|---|---|---|
| Parser version | `parser_version` | text |
| Chunking version | `chunking_version` | text |
| Chunk size | `chunk_size` | whole number, 1 to 1,000,000 |
| Chunk overlap | `chunk_overlap` | whole number, 0 to 1,000,000 |
| Embedding model | `embedding_model` | text |
| Embedding model version | `embedding_model_version` | text |
| Embedding dimensions | `embedding_dim` | whole number, 1 to 65,536. Also compared with every collection's vector size. |
| Preprocessing | `preprocessing` | text |

### Repair worker

Where: **Integrations**, Repair webhook card. Detail: [Integrations](12-integrations.md).

| Label | Internal key | Type | Required | Secret | Default |
|---|---|---|---|---|---|
| Webhook URL | `webhook_url` | address | No | No | none |
| Signing secret | `webhook_secret` | text | No (but nothing is sent without it) | Yes | none |
| Vector removal | `cleanup_policy` | `manual`, `auto` | No | No | `manual` |

### Alerts

Where: **Alerts**, Alert webhook card. Detail: [Alerts](13-alerts.md).

| Label | Internal key | Type | Secret | Default |
|---|---|---|---|---|
| Webhook URL | `webhook_url` | address (a Slack-compatible incoming webhook) | Yes | none |
| Minimum severity | `min_severity` | `critical`, `high`, `medium`, `low` | No | `high` |

### Audit policy

Where: **Settings**, **Policy** tab, card "Audit policy". Detail: [Settings](14-settings.md).

| Label | Internal key | Type and range | Default |
|---|---|---|---|
| Grace period (minutes) | `grace_minutes` | whole number, 0 to 1,440 | 10 |
| Default tenant | `default_tenant` | text. Assumed when a manifest row or a vector names no tenant. | `default` |
| Required payload fields | `required_payload_fields` | comma-separated names | empty (meaning `document_id` and `source_hash`, plus `tenant_id` once there is more than one tenant) |
| Only audit documents found in the source (S3) | `source_documents_only` | switch | off |
| Embedding price (USD per 1M tokens) | `embedding_price_per_mtok` | number, 0 to 10,000 | 0.13 |
| Tokens per chunk (for estimates) | `chunk_size_tokens` | whole number, 1 to 100,000 | 512 |

The two fields named **Default tenant** are different. The S3 one is used when the key pattern has no tenant group; the Policy one is used when a manifest row or a vector has no tenant.

API keys are a separate list on **Integrations**, not a settings group. See [API roles and endpoints](#api-roles-and-endpoints).

## API roles and endpoints

Every web-interface action is also an API call. The technical reference lists every endpoint ([GUIDE.md](../../GUIDE.md) section 9), and the server's interactive reference is at `/docs` on your RAGGuard address (the interface does not link to it).

| Role | How you prove it | Can do |
|---|---|---|
| Public | Nothing | Load the web interface, check `/healthz`, read the session status, sign up and sign in (rate limited) |
| Browser session | The `ragi_session` cookie set when you sign in | Everything in the interface, including settings, API keys and password |
| API key | `Authorization: Bearer ragi_...` | Run audits and read results, work with issues, documents, reports, isolation results and the isolation drill, recommendations, impact analysis, history and repair plans (including creating, triggering, verifying and approving cleanup), and send retrieval logs. It **cannot** read or change settings, test connections, list, create or revoke keys, or change a password. A key works only inside its own workspace. |
| Signed callback | An HMAC signature header, not a login | Your repair worker tells RAGGuard it has finished |

| Method | Path | Access | What it does |
|---|---|---|---|
| GET | `/` | Public | The web interface. Any other page address outside `/api`, `/static`, `/docs` and `/redoc` returns it too, so deep links work. |
| GET | `/healthz` | Public | Whether the server is up, its version and mode, whether the ledger is reachable and whether set-up is still required |
| GET | `/api/session` | Public | Who you are, whether sign-up is open, whether set-up is required, whether your workspace is ready |
| POST | `/api/auth/register` | Public, 5 per hour per network | Create an account and sign in |
| POST | `/api/auth/login` | Public, 8 per account and 30 per network per 15 minutes | Sign in |
| POST | `/api/auth/logout` | Browser session | End this session |
| POST | `/api/auth/password` | Session only, 10 per 15 minutes | Change the password and sign out other sessions |
| GET | `/api/settings` | Session only | Every settings group with its fields (never secrets) |
| PUT | `/api/settings/{kind}` | Session only | Save one group: `s3`, `manifest`, `qdrant`, `pipeline`, `repair`, `alerts` or `policy` |
| POST | `/api/settings/{kind}/test` | Session only, 30 per 10 minutes | Run the real check; with a body, test unsaved values |
| GET, POST | `/api/keys` | Session only | List API keys, create one (token shown once) |
| DELETE | `/api/keys/{key_id}` | Session only | Revoke a key |
| GET | `/api/overview` | Session or key | Health, counts, trend, latest runs |
| GET | `/api/connections` | Session or key | Live status of each connection |
| POST | `/api/audits` | Session or key | Start an audit. Body fields: `tenant`, `documents` (list of `tenant_id` and `document_id`), `probe`, `wait` (true to wait for the result) |
| GET | `/api/audits` | Session or key | Recent runs (`limit` 1 to 200, default 30) |
| GET | `/api/audits/{run_id}` | Session or key | One run |
| GET | `/api/issues` | Session or key | Issues. Filters: `status` (`open`, `resolved`, `ignored`, `all`; default `open`), `severity`, `type`, `tenant`, `q`, `limit` (1 to 500, default 100), `offset`. The answer has `total` and `items`. |
| GET | `/api/issues/{issue_id}` | Session or key | One issue with its events |
| POST | `/api/issues/{issue_id}/ignore` | Session or key | Ignore, with an optional `reason` (up to 500 characters) |
| POST | `/api/issues/{issue_id}/reopen` | Session or key | Reopen |
| GET | `/api/documents` | Session or key | Documents. Filters: `status`, `tenant`, `q`, `limit` (1 to 500), `offset` |
| GET | `/api/document` | Session or key | One document (`tenant`, `document_id`); `live=true` adds the live three-way view |
| GET | `/api/report` | Session or key | The integrity report: `format` (`json`, `md`, `csv`), `include_healthy`, `tenant` |
| GET | `/api/isolation` | Session or key | The tenant isolation picture of the latest full audit: overall and per-tenant status, five checks, and the issues open right now (`findings_live`, with `findings_changed_since_audit` set when they no longer match the audit). `available` is false before the first full audit. See [Isolation](20-isolation.md#the-api). |
| GET | `/api/isolation/report` | Session or key | The isolation evidence report: `format` (`json`, the default, or `md`) |
| POST | `/api/isolation/drill` | Session or key | The read-only isolation drill on one document. Optional body: `tenant` and `document_id`, both or neither. It changes nothing and sends nothing; `would_alert` holds the real alert message an audit would post, with `sent` set to false. |
| GET | `/api/recommendations` | Session or key | Recommended work and cost; optional `min_severity` |
| POST | `/api/blast-radius` | Session or key | Impact analysis |
| POST | `/api/setup-check` | Session or key, 20 per 10 minutes per workspace | The setup check: do S3, the manifest and Qdrant call the same documents by the same ID? No body. Read-only, stores nothing, can take up to about two minutes. Always answers 200, even when a connection is missing (then the verdict is `not_ready`) |
| POST | `/api/query-log` | Session or key | Send retrieval logs (up to 5,000 rows per call) |
| GET | `/api/history` | Session or key | The merged activity trail (`limit` 1 to 500, default 100) |
| POST, GET | `/api/repairs` | Session or key | Create a plan, list plans |
| GET | `/api/repairs/{plan_id}` | Session or key | One plan with its events |
| GET | `/api/repairs/{plan_id}/payload` | Session or key | The request that would be sent to your worker |
| POST | `/api/repairs/{plan_id}/trigger` | Session or key | Send the re-index request to your worker |
| POST | `/api/repairs/{plan_id}/verify` | Session or key | Verify the plan's documents |
| POST | `/api/repairs/{plan_id}/approve-cleanup` | Session or key | Ask your worker to remove the old vectors |
| POST | `/api/repairs/{plan_id}/callback` | Signed callback | Your worker reports it has finished; this starts verification |

HTTP status codes you may see from the API: `400` the request could not be carried out (the message says why, for example the isolation drill needs both `tenant` and `document_id`, or neither); `401` sign in or a valid key is needed; `403` not allowed (for example a key used for settings); `404` not found; `409` set-up incomplete or an audit already running; `422` a value was rejected (the message names the field); `429` rate limited; `502` your infrastructure refused or failed (the message explains); `503` the connection or the deployment is not set up; `504` the audit ran out of time.

## Limits and rate limits

| Limit | Value | Where it applies and what you see |
|---|---|---|
| Password length | 10 to 128 characters | Sign-up and Change password |
| Sign-in attempts | 8 per account and 30 per network per 15 minutes | "Too many sign-in attempts. Wait a few minutes and try again." A successful sign-in clears the per-account count. |
| Sign-ups | 5 per network per hour | "Too many sign-ups from your network. Try again later." |
| Password changes | 10 per account per 15 minutes | "Too many attempts. Try again later." |
| Connection tests | 30 per workspace per 10 minutes | "Too many connection tests. Try again in a few minutes." |
| Session lifetime | 7 days, renewed as you use the app (set by the server operator) | You are sent back to sign in when it ends |
| Workspaces | One per account | |
| API keys | 20 per workspace | "You can have at most 20 API keys. Revoke one first." |
| API key name | 80 characters | The field says "Use at most 80 characters." |
| API key "Last used" | Updated at most once every 10 minutes | |
| Concurrent audits | One per workspace | "An audit is already running." |
| Audit time budget, hosted | 270 seconds (the hosting function stops at 300) | The audit stops with a message saying which step was running |
| Audit time budget, other servers | None unless the operator sets one | |
| One Qdrant request, hosted audit | Up to 60 seconds | A slow filter fails with a clear "timed out" message |
| Connection test timeouts | S3: 4 seconds to connect, 10 to read, no retries. Qdrant: 8 seconds. Manifest: 10 seconds to connect. | |
| Manifest query time | 45 seconds per statement | |
| Abandoned-run clean-up | A run still Running after the time budget plus 90 seconds (360 seconds on hosted servers) is marked Failed. Without a time budget the wait is 15 minutes. | The **Run audit** button is enabled again |
| Retrieval probes | Up to 25 per audit, each reading the top 10 results | Only for orphan, tenant-mismatch, stale and superseded findings |
| Scoped audit by documents (API) | Up to 5,000 documents; tenant up to 256 characters; document id up to 2,048 | |
| Ids in evidence | Up to 50 chunk or point names listed; up to 5,000 point ids per collection in a removal list | Marked as truncated when capped |
| Repair plan creation | Up to 5,000 issue ids and 20 types | |
| Repair webhook | One attempt, 30-second wait; signature accepted within 5 minutes | "Repair webhook delivery failed: ..." |
| Alert webhook | One attempt, 10-second wait, no retry; up to 10 issues in the text and 25 in the list | Recorded on the run |
| Retrieval log | Up to 5,000 rows per call, up to 100 document ids per row; searches from the last 14 days count | |
| Lists in the interface | The first 500 issues and 500 documents are loaded (sorted and paged in the browser, 25 rows per page by default); the 100 most recent audits; the 200 most recent activity events; the latest 50 audits for Recent deliveries; the 50 most recent repair plans; the most severe 200 documents in the Recommended work preview (a plan includes all); the first 500 chunks in a live inspection | A note under the table says when more exist |
| Impact analysis | A sample of 25 affected documents; the top 8 documents in Query impact | |
| Tests | S3 lists up to 200 keys and reads details of 5; manifest counts up to 100,000+ rows; Qdrant checks the first 5 collections and samples 20 points | |
| Ignore reason | 500 characters | |

## Glossary

| Term | Meaning |
|---|---|
| Access-control hash (ACL hash) | A fingerprint of a document's permissions. RAGGuard compares the one in the manifest with the one on the vectors. |
| API key | A token (`ragi_...`) for scripts and CI. Shown once, stored only as a hash, works inside one workspace. |
| Audit | One comparison of source, manifest and index. It produces issues, document statuses and a health score. |
| Chunk | A piece of a document that is turned into one vector |
| Collection | A named set of vectors inside Qdrant |
| Collection-level finding | A finding about a whole collection, not about one document |
| Document id | The stable identity of a document, taken from the S3 key (after the prefix and key pattern), the manifest `document_id` column and the payload `document_id` field. It must be written the same way in all three. |
| Embedding / vector | The list of numbers that represents a chunk for similarity search |
| ETag | An identifier S3 gives each object. For objects uploaded in several parts it is not a content hash, so RAGGuard flags it as unreliable. |
| Evidence | The values an audit read from your systems when it raised an issue |
| Fingerprint | The setup used to build a document's vectors: parser, chunking, embedding model and preprocessing |
| Grace period | How long a recently changed or still-processing document is allowed to be Pending before it is judged. Default 10 minutes. |
| Health score | The share of healthy (and pending) documents, as a percentage |
| HMAC | A signature computed with a shared secret. RAGGuard signs each request to your worker, and your worker signs its callback. |
| Index | The vector database your application searches (Qdrant) |
| Issue | One recorded disagreement, with a type, a severity, evidence and a recommended fix |
| Issue ledger | RAGGuard's own database of runs, issues, document states and plans. It never stores document contents. |
| Key pattern | The regular expression that turns an S3 key into a tenant and a document id |
| Key prefix | Only keys under this prefix are audited |
| Manifest | The table where your pipeline records what it processed |
| Orphan | Something that no longer has an owner: vectors for a deleted document, or a manifest row for one |
| Payload | The metadata stored with each vector (document id, hash, chunk id, and so on) |
| Pending | A document that changed or is being processed within the grace period, so it is not judged yet |
| Pipeline drift | Vectors built with a different setup than your target pipeline |
| Point | One stored vector with its payload, in Qdrant |
| Probe (retrieval probe) | A search against the live index, using one affected chunk's own vector, to show whether bad content can really be returned |
| Public address | A host that is reachable from the internet. Hosted mode refuses private network and `localhost` addresses. |
| RAG | Retrieval-augmented generation: answers are written from documents retrieved from a vector index |
| Read-only | RAGGuard only lists, reads and queries your systems. It never writes or deletes. |
| Repair plan | A set of documents with the smallest safe action for each, which RAGGuard hands to your worker and then verifies |
| Scope | The part of the corpus an audit covers: everything, one tenant, or specific documents |
| Session | Your signed-in browser connection, kept in a cookie |
| `source_hash` | The SHA-256 of a document as your pipeline last processed it. RAGGuard compares it with the hash read from S3. |
| Source | The documents in S3 that should be searchable |
| Target pipeline | The setup you expect documents to have been processed with, set in Settings |
| Tenant | A customer or business unit whose documents must stay separate |
| Webhook | An address that receives an automatic HTTP request. RAGGuard uses one for repairs and one for alerts. |
| Worker | Your own program that re-indexes documents when RAGGuard asks |
| Workspace | One account's private area: its connections, issues, history and plans |

## Related chapters

- [Concepts you need](02-concepts.md)
- [Connect your data sources](04-data-sources.md) and [Settings](14-settings.md)
- [Integrity issues](07-integrity-issues.md), [Repair plans](08-repair-plans.md), [Isolation](20-isolation.md) and [Documents](10-documents.md)
- [Audit history](11-audit-history.md), [Integrations](12-integrations.md) and [Alerts](13-alerts.md)
- [End-to-end journey](15-end-to-end-journey.md), [Practical use cases](16-use-cases.md) and [Troubleshooting](18-troubleshooting.md)
