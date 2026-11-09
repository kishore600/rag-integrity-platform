const e=`# Concepts you need

RAGGuard uses a small set of words again and again: source, manifest, index, tenant, audit, issue, severity, health score and a few more. This chapter explains each one in plain language, with an example and a note on where you see it in the interface. Read it once now, and come back whenever a word on screen is unfamiliar. Every definition here was checked against the product's code, so the thresholds, statuses and rules you read are the ones RAGGuard really applies.

**On this page**

- [The three systems RAGGuard compares](#the-three-systems-ragguard-compares)
  - [Source, manifest and index](#source-manifest-and-index)
- [How things are identified](#how-things-are-identified)
  - [Tenant](#tenant)
  - [Document id](#document-id)
  - [Chunk](#chunk)
  - [Vector, point and embedding](#vector-point-and-embedding)
  - [Payload](#payload)
  - [Hash and version](#hash-and-version)
- [Audits](#audits)
  - [Audit](#audit)
  - [Retrieval probe](#retrieval-probe)
  - [Grace period](#grace-period)
- [Problems the audit reports](#problems-the-audit-reports)
  - [Finding and issue](#finding-and-issue)
  - [Issue lifecycle](#issue-lifecycle)
  - [Severity](#severity)
  - [Ledger](#ledger)
- [How documents are classified](#how-documents-are-classified)
  - [Document status](#document-status)
  - [Document states shown in tables](#document-states-shown-in-tables)
  - [Vector classes](#vector-classes)
  - [Health score](#health-score)
  - [Pipeline fingerprint and drift](#pipeline-fingerprint-and-drift)
  - [The many meanings of orphan](#the-many-meanings-of-orphan)
- [Fixing problems](#fixing-problems)
  - [Repair plan](#repair-plan)
  - [Signed webhook](#signed-webhook)
  - [Cleanup](#cleanup)
  - [Blast radius](#blast-radius)
- [Accounts and access](#accounts-and-access)
  - [Workspace](#workspace)
  - [Server modes and demo data](#server-modes-and-demo-data)
  - [Read-only access](#read-only-access)
  - [API key](#api-key)
- [Related chapters](#related-chapters)

---

## The three systems RAGGuard compares

### Source, manifest and index

**What they are.** A RAG system (retrieval-augmented generation) answers questions by first searching an index of your documents and then handing the best matches to a language model. Behind that index sits an **ingestion pipeline**: software you run that reads documents, splits them into pieces, turns the pieces into numbers and stores them. RAGGuard does not run your pipeline. It checks the pipeline's work by reading three places:

| Word in RAGGuard | System | What it holds | The question it answers |
|---|---|---|---|
| **Source** | Amazon S3 (or an S3-compatible store) | The original documents | What exists right now? |
| **Manifest** | A PostgreSQL table | One row per document: what your pipeline believes it did | What did the pipeline think it did? |
| **Index** | A Qdrant collection (or several) | The vectors your application actually searches | What is really searchable? |

A **collection** is Qdrant's name for a named group of vectors, a little like a table. In the Qdrant settings you can list the collections to audit. If you leave the list empty, RAGGuard audits every collection.

The manifest is written by your pipeline, not by RAGGuard. RAGGuard understands these values of its status column, whatever the capitalisation:

| Meaning | Values RAGGuard recognises |
|---|---|
| Success | success, succeeded, indexed, completed, complete, done, ready, ok, processed, true |
| In flight (still being processed) | pending, queued, processing, running, in_progress, indexing, parsing, embedding |
| Failed | failed, error, errored, failure |
| Deleted | deleted, tombstoned, removed |

The value \`true\` is on the success list so that a true or false column such as \`is_indexed\` can be used as the status.

**Example.** The policy document \`policies/leave-policy.md\` is in S3 (source). Your pipeline recorded status \`success\` with 7 chunks (manifest). Qdrant holds no vectors for it (index). Anyone who asks about leave rules never gets that document, and nothing in your pipeline's logs says so. RAGGuard reports it as **Missing embeddings**, and because the manifest claims success it marks it **Critical**.

**Where you see it.** The three-way comparison on [Reconciliation](06-reconciliation.md), the **Connection health** card on the [Overview](05-overview.md), and the "Where this document exists" section of a document's panel in [Documents](10-documents.md).

---

## How things are identified

### Tenant

**What it is.** A tenant is one customer, team or business unit whose documents must stay separate from everyone else's. RAGGuard identifies every document by the pair (tenant, document id), so the same document id under two tenants is two different documents.

Where RAGGuard reads the tenant from:

| System | Where the tenant comes from |
|---|---|
| S3 | The \`tenant_id\` part of the **Key pattern**. The default pattern treats the first folder as the tenant. |
| Manifest | The \`tenant_id\` column, if your table has one. |
| Index | The \`tenant_id\` payload field on each vector. |

When a place has no tenant, RAGGuard uses a default tenant, which starts as \`default\`. There are two **Default tenant** settings: one in the S3 settings (used for keys that carry no tenant) and one in **Audit policy** (used for rows and vectors that carry none). Keep them equal.

**Example.** With the default key pattern, the S3 key \`customer-a/policies/leave-policy.md\` belongs to tenant \`customer-a\`. If your bucket has no tenants, change the key pattern to \`^(?P<document_id>.+)$\` and every document lands in the default tenant.

**Where you see it.** The **Tenant** columns and filters, the **Tenant health** card on the Overview, the tenant choice in a scoped audit, and the **Isolation** page, which checks that no tenant's documents are indexed under another tenant ([Isolation](20-isolation.md)).

### Document id

**What it is.** The stable name of a document inside its tenant. With the default key pattern it is everything after the first slash of the S3 key.

| S3 key | Tenant | Document id |
|---|---|---|
| \`customer-a/policies/leave-policy.md\` | \`customer-a\` | \`policies/leave-policy.md\` |
| \`customer-b/runbooks/restore-database.md\` | \`customer-b\` | \`runbooks/restore-database.md\` |

The same id must appear in the manifest's \`document_id\` column and in the \`document_id\` payload field of every vector. If the three systems spell it differently, RAGGuard sees three unrelated documents instead of one.

If several S3 files or several manifest rows carry the same document id (for example one bill made of many PDFs), RAGGuard folds them into one document: sizes are added and the content hashes are combined into one. A manifest status counts as success only when every row succeeded.

**A special id.** Some findings belong to a whole collection instead of one document, for example vectors that carry no document id at all. Their document id is \`*\`. The interface shows it as **Whole tenant** in lists and explains "This finding applies to the whole collection" in the issue panel. These findings cannot be put into a repair plan.

**Where you see it.** The **Document** column shows the file name with the full id underneath. Hover over a name to see the full id.

### Chunk

**What it is.** A piece of a document. Pipelines cut documents into chunks (usually a few paragraphs each) because search works on small pieces. Each chunk becomes one vector in the index.

RAGGuard works out which chunks a document should have from, in this order of preference:

1. An optional **chunk table** in your database that lists every chunk id (exact).
2. The manifest's \`expected_chunk_count\`.
3. Gaps in the chunk numbers found in the index (a guess, labelled "suspected").

**Example.** The manifest says \`leave-policy.md\` should have 7 chunks, but the index holds 5. RAGGuard reports **Partial index**: "2 expected chunk(s) are missing from the index (5 indexed vs 7 expected)". Users get answers built from only part of the policy.

**Where you see it.** The **Chunks** column in Documents shows indexed over expected, for example \`5 / 7\`, in amber when they differ. The **Chunks** tab of a document's panel lists every chunk after **Inspect live**.

### Vector, point and embedding

**What they are.**

- An **embedding** is a long list of numbers, produced by an embedding model, that captures the meaning of a chunk. Chunks with similar meaning get similar numbers.
- A **vector** is that list of numbers as stored in the index.
- A **point** is Qdrant's word for one stored vector together with its payload. RAGGuard's screens say "vectors"; evidence text sometimes says "points". They mean the same thing here.

One chunk normally equals one point. Two points for one chunk is a duplicate. A point whose vector is missing, empty or all zeros can never match a search; that is an **Empty embeddings** issue, and RAGGuard only looks for it when **Detect empty embeddings** is on in the Qdrant settings, because it has to download the vectors.

**Example.** A document with 7 chunks should have 7 points. If a retried job wrote every chunk twice, it has 14 points: that is **Duplicate chunks**.

**Where you see it.** The **Index vectors** tile in the three-way comparison and on an audit's page, and the vector counts in a document's live inspection.

### Payload

**What it is.** The labels stored next to each vector in Qdrant. RAGGuard reads the payload to learn which document and chunk a vector belongs to and which version of the document it was built from.

The fields RAGGuard looks for are:

| Purpose | Payload fields |
|---|---|
| Identity | \`tenant_id\`, \`document_id\`, \`chunk_id\`, \`chunk_index\`, \`chunk_hash\` |
| Freshness | \`source_hash\`, \`source_version\` |
| Pipeline fingerprint | \`parser_version\`, \`chunking_version\`, \`chunk_size\`, \`chunk_overlap\`, \`embedding_model\`, \`embedding_model_version\`, \`embedding_dim\`, \`preprocessing\` |
| Permissions | \`acl_hash\` |

If your payload uses other names, a **Payload field map** in the Qdrant settings translates them. At minimum every vector needs \`document_id\` and \`source_hash\`, plus \`tenant_id\` once you have more than one tenant. You can change this list with the **Required payload fields** setting; a vector that lacks a required field produces a **Metadata mismatch** issue.

**Example.**

\`\`\`json
{
  "tenant_id": "customer-a",
  "document_id": "policies/leave-policy.md",
  "chunk_id": "policies/leave-policy.md#3",
  "chunk_index": 3,
  "source_hash": "9f2c0a...e1"
}
\`\`\`

### Hash and version

**What they are.**

- A **source hash** is a short fingerprint (SHA-256) of a document's content. If the content changes by even one character, the hash changes. It is how RAGGuard knows a document changed.
- A **source version** is the S3 version id when your bucket uses versioning, otherwise the file's ETag.
- The **indexed version** is the version the index actually holds. RAGGuard reads it from the vector payloads and falls back to what the manifest claims.

RAGGuard compares the hash S3 reports now with the hash stored on each vector. A different hash means the vector describes an older version of the document.

The setting **Content hash** decides how RAGGuard gets the hash from S3:

| Mode | How the hash is obtained | Cost |
|---|---|---|
| \`metadata\` (default) | The SHA-256 stored with the object (the user-metadata key \`sha256\` by default) or S3's own SHA-256 checksum | One small request per object |
| \`compute\` | RAGGuard downloads each object, hashes it and discards the contents | Download traffic and time |
| \`etag\` | The ETag | None extra, but a multipart-upload ETag is not a content hash |

Whatever mode you choose, your pipeline must write the same value as \`source_hash\` into the manifest and into each vector's payload. Otherwise every document looks stale.

**Example.** On Monday the pipeline indexes a policy and stores hash \`9f2c...\`. On Tuesday someone edits the file in S3, and its hash becomes \`41ab...\`. The vectors still say \`9f2c...\`, so RAGGuard reports **Stale document version**.

**Where you see it.** The **Source** and **Indexed** columns in Documents show shortened versions, with a warning triangle when they differ. The Overview tab of a document's panel shows the hash and version values.

---

## Audits

### Audit

**What it is.** One run of RAGGuard's comparison. An audit reads the source, the manifest and the index, compares them document by document, and records what it found. It only reads. It never changes your systems.

An audit does these steps:

1. Lists the documents in S3 (or, when **Look up files from the manifest** is on, reads exactly the files the manifest names).
2. Reads the manifest rows, and the chunk table if you configured one.
3. Scans the index and classifies every vector (see [Vector classes](#vector-classes)).
4. Compares the three views of each document and records findings.
5. Sends retrieval probes for the most worrying findings (see [Retrieval probe](#retrieval-probe)).
6. Updates the issue ledger: new issues are opened, known ones are updated, fixed ones are resolved.
7. Sends an alert if you set up alerts and there is something new to report.
8. Records the run, its statistics and its duration.

There are three kinds of audit:

| Kind | What it covers | Started by | Notes |
|---|---|---|---|
| **Full** | Everything: every tenant and every document | **Run audit** or **Run full audit** in the interface, an API call, or a schedule on a single-user server | The only kind drawn in **Health over time**. Also runs the checks that apply to a whole collection. |
| **Scoped** | One tenant, or a list of documents you chose | **Scoped audit** on Reconciliation, or **Re-audit document** in a document's panel | Only resolves issues inside its own scope. The run's health score covers only its own documents. |
| **Verify** | The documents of one repair plan | RAGGuard itself, when you press **Verify now**, when your worker calls back, or when you approve a cleanup | Retrieval probes are switched off. You cannot start one by hand. |

Only one audit can run at a time in a workspace. If you start a second one, RAGGuard refuses it with a message such as "An audit is already running." On serverless hosting, which includes the hosted service, an audit that has not finished within its time budget (270 seconds by default) stops with an error that names the step it was in. For a very large corpus, audit one tenant at a time. Chapter [Troubleshooting](18-troubleshooting.md) lists the messages.

**Where you see it.** The **Run audit** button, the **Last audit** card, and every row of [Audit history](11-audit-history.md).

### Retrieval probe

**What it is.** Having a bad vector is one thing. Whether a user can actually be served it is what matters. A retrieval probe answers that. For a finding about content that should not be searchable (deleted documents, old versions, superseded vectors, wrong-tenant vectors), RAGGuard picks one affected chunk and searches the live index with that chunk's own vector. The search uses the same tenant filter a real query would use. RAGGuard then checks whether the bad vector appears among the top 10 results, and at what rank.

By default an audit sends at most 25 probes. They are sent in this order of priority: wrong-tenant vectors first, then orphan vectors, then stale versions, then superseded vectors.

A probe is a stand-in for "a user asks something that matches this chunk". It proves that the content is searchable and shows what it competes with. It does not replay real user traffic.

**How it can raise a severity.** If a probe shows the bad content is reachable:

| Finding | Severity before | Severity after |
|---|---|---|
| **Orphan vectors** | High | **Critical** |
| **Superseded vectors active** | Medium | **High** |

Findings of other types are probed too, and their evidence records the rank, but their severity does not change. A severity change after a probe also recalculates the document's status. If the issue was already open, the audit counts it as **Escalated**.

**Example.** A deleted policy still has 12 vectors. The probe asks Qdrant a question that matches one of them, and the old policy comes back at rank 2. The finding goes from High to Critical, with the sentence "Confirmed: it is returned at rank 2 for a query matching it."

**Where you see it.** The **Retrieval probes** row in **Last audit** and on a run's page, and the **Retrieval probe** table in an issue's evidence ([Integrity issues](07-integrity-issues.md)).

### Grace period

**What it is.** A document that was just changed, or is being processed right now, is probably still on its way into the index. If RAGGuard judged it immediately, every upload would look like a failure. The grace period is how long RAGGuard waits before judging. The default is 10 minutes. You change it with **Grace period (minutes)** in **Audit policy** (0 to 1,440; 0 switches it off).

A document is **pending**, not broken, when it has no findings and one of these is true:

- It has no vectors yet, and its S3 file was modified within the grace period.
- It has no vectors yet, and its manifest status is in flight and was last updated within the grace period (or has no update time).
- Every vector it has is from an older version, and the S3 file was modified within the grace period.

When the grace period is over and the document is still not indexed, RAGGuard reports it. A document that has been stuck in \`processing\` for longer than the grace period is reported as **Missing embeddings**, with the reason "The pipeline has had this document in 'processing' since ...".

**Example.** You upload a contract at 10:00. An audit at 10:04 sees no vectors yet, but the file is 4 minutes old, so the contract is **Pending**. An audit at 10:30 still sees no vectors, so it is reported.

**Where you see it.** The **Pending** status and the **Processing** state in Documents.

---

## Problems the audit reports

### Finding and issue

**What they are.**

- A **finding** is one problem that one audit detected. It exists for that audit's results.
- An **issue** is RAGGuard's lasting record of a problem. Every finding becomes an issue, and the same problem found by later audits updates the same issue instead of creating a new one.

RAGGuard decides "same problem" from four things: the issue type, the tenant, the document and the collection. As long as those match, it is one issue with a growing history. The number of audits that saw it is shown as **Seen in audits**.

There are 11 issue types: Missing embeddings, Partial index, Stale document version, Superseded vectors active, Orphan vectors, Duplicate chunks, Metadata mismatch, Pipeline drift, Empty embeddings, Tenant mismatch and Orphan manifest row. [Integrity issues](07-integrity-issues.md) explains each one, and [Reference: every value](17-reference.md) lists them all.

**Example.** An audit on Monday finds that \`leave-policy.md\` has no vectors. That finding opens an issue. An audit on Tuesday finds the same thing: no new issue, but **Seen in audits** goes from 1 to 2 and **Last seen** moves forward.

**Where you see it.** The audit page says "Findings" and "issues found". Everywhere else the interface says "issues".

### Issue lifecycle

An issue is always in one of three states: **Open**, **Resolved** or **Ignored**. Two more words, **reopened** and **escalated**, describe things that happen to an issue during an audit.

| Word | What it means | How it happens | Where you see it |
|---|---|---|---|
| **Open** | The problem exists. | An audit finds it. | Amber status badge. Counted in **Open issues**. |
| **Resolved** | The problem is gone. | An audit that covers the document no longer finds it. | Green status badge. The timeline says "Resolved: the index now matches the source". |
| **Ignored** | You decided to leave it. | You press **Ignore**, optionally with a reason of up to 500 characters. | Grey status badge. No longer counted as open and left out of repair plans. The reason is kept. |
| **Reopened** | A problem that had been resolved came back. | An audit finds a resolved issue again. It becomes Open again and its reopened count goes up. | Counted as **Reopened** in the audit's changes. The timeline says "Came back after it was resolved". |
| **Escalated** | An open issue became more severe. | An audit finds the same open issue at a higher severity, for example after a probe confirms the content is reachable. | Counted as **Escalated** in the audit's changes. The timeline says "Severity changed from High to Critical". |

Details worth knowing:

- A **scoped or verify audit only resolves issues inside its own scope.** Checking three documents cannot close an issue about a fourth.
- An **ignored** issue stays ignored. If a later audit still finds it, RAGGuard keeps updating when it was last seen but does not reopen it or count it. If a later audit no longer finds it, it is not resolved automatically. Use **Reopen** to bring it back. Reopening an ignored issue is recorded in the timeline as "Reopened by a user", and in the activity log as "Issue unignored".
- When an audit reports its changes it uses five counts: **Opened** (new), **Reopened**, **Escalated**, **Resolved** and **Unchanged**. **Unchanged** counts every issue that was already open and was found again, including one whose severity changed, so an escalated issue is counted in both **Escalated** and **Unchanged**.
- If severity goes down, the timeline records "Severity changed" but no separate count is kept.
- Every change is written to the issue's timeline and to the [activity log](11-audit-history.md#the-activity-log-tab).

**Example.** Monday: an orphan-vector issue is opened as High. Tuesday: a probe shows the deleted content is returned, so it is escalated to Critical. Wednesday: your worker removes the vectors, and the audit resolves the issue. Next month: a bad import brings the vectors back, and the issue is reopened.

### Severity

**What it is.** How urgent an issue is. RAGGuard sets it from the issue type and from the evidence it read.

| Severity | Badge colour | What it usually means |
|---|---|---|
| **Critical** | Red | The pipeline claimed success but data is missing or partial, deleted content can really be returned, vectors sit under the wrong tenant, or a collection's vector size does not match your target model. |
| **High** | Amber | Missing, stale or empty embeddings, orphan vectors, permission (ACL) mismatches, embedding-model drift. |
| **Medium** | Blue | Duplicates, superseded vectors, chunking or parser drift, count mismatches, suspected gaps. |
| **Low** | Grey | Bookkeeping that does not affect users, such as a leftover manifest row. |

The product also has a fifth level, **info**, which audits do not produce today. It would appear only if a count for it existed.

How the severity of each issue type is chosen:

| Issue type | Usual severity | When it differs |
|---|---|---|
| Missing embeddings | High | **Critical** when the manifest claims success (a success status, or an indexed chunk count above 0) |
| Partial index | High | **Critical** when the pipeline claims success. **Medium** when it is only suspected from gaps in chunk numbers. |
| Stale document version | High | **Medium** when the S3 hash is a multipart ETag, which can change without the content changing |
| Superseded vectors active | Medium | **High** when a probe shows old content is returned |
| Orphan vectors | High | **Critical** when a probe shows the deleted content is returned |
| Duplicate chunks | Medium | |
| Metadata mismatch | The highest of its listed problems | Low, medium or high. Vectors without a document id are High. |
| Pipeline drift | Medium | **High** when the embedding model, its version or its dimensions differ. **Critical** when a collection's vector size differs from your target dimensions. |
| Empty embeddings | High | |
| Tenant mismatch | Critical | |
| Orphan manifest row | Low | |

**Where you see it.** Coloured badges everywhere, the severity chips on the Integrity Issues page, the donut on the Overview, and the bell menu in the top bar.

### Ledger

**What it is.** The database where RAGGuard stores its own results: audit runs, issues, the latest state of each document, repair plans and the history of changes. It stores identifiers, hashes, versions, counts and evidence about them. It never stores the contents of your documents. The server manages the ledger for you. It is not one of the three systems you connect.

**Where you see it.** The **Issue ledger** row in the **Connection health** card and on **Data Sources**.

---

## How documents are classified

### Document status

**What it is.** The result of the last audit that covered a document. It comes from the document's worst finding.

| Status | Rule | In plain words |
|---|---|---|
| **Healthy** | No findings | Source, manifest and index agree. |
| **Degraded** | The worst finding is medium or low | Searchable, with minor problems. |
| **Broken** | The worst finding is high or critical | Serious problems. |
| **Pending** | Inside the grace period and no findings | Still being processed, not judged yet. |
| **Orphaned** | Not in the source any more, but vectors remain | Deleted at the source, still searchable. |

RAGGuard checks pending first, then orphaned, then the severity rules. So an orphaned document stays **Orphaned** whatever the severity of its issue. A leftover manifest row with no file and no vectors has a low-severity issue and no vectors, so it shows as **Degraded**, not Orphaned.

If a probe raises a severity after the comparison, RAGGuard recalculates the status of every document except pending and orphaned ones.

**Example.** A document with one Medium issue (duplicate chunks) is **Degraded**. If it also has a High issue (stale version), it is **Broken**.

**Where you see it.** The **Document status** card on the Overview, the **Audit result** badge in a document's panel, and the filter choices **Healthy**, **Needs attention** (degraded plus broken), **Degraded**, **Broken**, **Pending** and **Orphaned**.

### Document states shown in tables

**What they are.** In the document tables the badge is a simpler, embedding-focused label: **Healthy**, **Stale**, **Missing embeddings**, **Processing** or **Failed**. It is worked out from the document's status and its issue types. RAGGuard applies these rules in order, and the first rule that matches wins:

| Order | If the document... | The table shows | Badge colour |
|---|---|---|---|
| 1 | has status **Pending** | **Processing** | Blue |
| 2 | has a **Missing embeddings** issue | **Missing embeddings** | Red |
| 3 | has a **Stale document version** issue | **Stale** | Amber |
| 4 | has status **Healthy** | **Healthy** | Green |
| 5 | has status **Broken** or **Orphaned** | **Failed** | Red |
| 6 | is anything else (that is, **Degraded**) | **Stale** | Amber |

Rule 6 reuses the label **Stale**. A document whose only problem is duplicate chunks or a metadata mismatch is Degraded, so its table badge reads **Stale** even though its content is current. Open the document's panel and look at the **Issues** tab and the **Audit result** badge to see the real problem.

**Where you see it.** The **Embedding status** column in Documents, the **Status** column in the Reconciliation documents table, and the badge at the top of a document's panel.

### Vector classes

**What they are.** While scanning the index, RAGGuard gives every vector one of five classes by comparing it with the live source and with your target pipeline.

| Class | Meaning | Example |
|---|---|---|
| **fresh** | Its hash or version matches the live source, and its pipeline fingerprint does not conflict with your target. | A vector built from today's file with today's settings. |
| **stale** | Its hash or version differs from the live source. It describes an older version of the document. | A vector built before the file was edited. |
| **outdated** | The content is current, but it was built with a different parser, chunker or embedding setup than your target. | A vector built with last year's embedding model. |
| **unknown** | The payload carries no hash or version, so RAGGuard cannot tell from the index whether it is current. | A vector with no \`source_hash\`. |
| **orphan** | The document no longer exists in the source. | A vector for a deleted file. |

The order matters: RAGGuard decides "orphan" first, then "stale", then "outdated". A vector is **live** when it is fresh or unknown: these are the vectors that count as the document's current content. Live vectors are what the completeness and duplicate checks look at.

**Where you see it.** In the **Chunks** tab of a document's panel after **Inspect live**: a **Class** column, count badges per class, and a one-line explanation of each class.

### Health score

**What it is.** One percentage for "how much of my index can I trust". RAGGuard computes it as:

> health score = (documents that are Healthy + documents that are Pending) ÷ all documents × 100, rounded to one decimal

**Pending** documents count as healthy because RAGGuard has not judged them yet. **Degraded**, **Broken** and **Orphaned** documents count as not healthy.

**Example.** A workspace knows 200 documents: 170 Healthy, 10 Pending, 12 Degraded, 6 Broken and 2 Orphaned. The score is (170 + 10) ÷ 200 = 90.0%.

**Colours.** RAGGuard colours a score like this:

| Score | Colour |
|---|---|
| 90% or higher | Green |
| 70% or higher, below 90% | Amber |
| Below 70% | Red |
| No score yet | Grey, shown as a dash |

The earlier reference file \`GUIDE.md\` says 95 and 80. The product's code uses 90 and 70, and this guide follows the code.

**Two scores to tell apart.**

- The **workspace score** (Overview card, and each tenant in **Tenant health**) is calculated from the latest known status of every document. Scoped audits update the documents they covered, so this score is always current across the whole workspace. It has no value until at least one document is known.
- A **run score** (a row in Audit history, the tile on an audit's page, the **Three-way comparison** on Reconciliation) covers only the documents that one audit compared. A scoped audit's score covers only its scope. A run that compared no documents scores 100.0.

A high score means RAGGuard found no disagreement in the data it could read. If your vector payloads carry no \`source_hash\`, for example, RAGGuard cannot see that a document is stale. See [Hash and version](#hash-and-version).

**Where you see it.** The **Health score** card, **Health over time**, **Tenant health**, the **Health** column in Audit history and the **Health score** tile on an audit's page.

### Pipeline fingerprint and drift

**What the fingerprint is.** The recipe a document was turned into vectors with. It has eight parts:

| Part | Example |
|---|---|
| Parser version | \`parser-2.1\` |
| Chunking version | \`recursive-v2\` |
| Chunk size | a whole number |
| Chunk overlap | a whole number |
| Embedding model | the model's name |
| Embedding model version | its version |
| Embedding dimensions | how many numbers each vector has |
| Preprocessing | a label for your cleaning step |

Each vector's fingerprint comes from its payload. Any part the payload leaves out is filled in from the document's manifest row.

**What the target is.** The recipe documents *should* currently be built with. You describe it in **Settings**, on the **Pipeline** tab (the **Target pipeline** group). All its fields are optional.

**What drift is.** A difference between the fingerprint a document was built with and the target. RAGGuard only compares parts where both sides know a value. It reports drift in three cases:

1. A document's content is current, but all its vectors were built with a recipe that conflicts with the target. The vectors are classed **outdated**.
2. The live vectors of one document disagree with each other, for example two embedding models in one document. This needs no target.
3. The target's embedding dimensions differ from a collection's vector size. This one affects the whole collection and is **Critical**, because queries embedded with the target model cannot match that collection.

Severity for 1 and 2 is **High** when the embedding model, its version or its dimensions differ, and **Medium** for chunking, parser or preprocessing differences.

**Example.** You move to a new embedding model and set it as the target. Documents indexed with the old model are drift (High) until your pipeline re-embeds them. Mixing two models in one index degrades search quality in ways that are hard to see.

**Where you see it.** The **Pipeline fingerprint** section of a document's panel, the **Pipeline drift** issue type, and the **Pipeline change** scenario in [Impact analysis](09-impact-analysis.md).

### The many meanings of orphan

The word **orphan** always means "gone from the source", but it appears in four places:

| Where | Name | What it means |
|---|---|---|
| Issue type | **Orphan vectors** | A document was deleted, but its vectors are still searchable. |
| Issue type | **Orphan manifest row** | The manifest still lists a document that is gone from both the source and the index. |
| Document status | **Orphaned** | The document is not in the source, but vectors remain. |
| Vector class | **orphan** | This vector belongs to a document that no longer exists in the source. |

If the "deleted" document id still exists under a different tenant, RAGGuard does not call it an orphan. It reports **Tenant mismatch** instead, because the vectors were probably filed under the wrong tenant and could leak content between customers.

---

## Fixing problems

### Repair plan

**What it is.** A saved list of what to do about open issues, one entry per document. RAGGuard chooses the smallest safe action for each document:

| Action label | What it means | Used for |
|---|---|---|
| Full reindex | Process the whole document again: parse, chunk, embed, store and update the manifest. | Missing, stale, drifted or empty embeddings |
| Re-embed missing chunks | Embed only the chunks that are missing. | Partial index |
| Fix metadata | Correct the manifest or payload values. No re-embedding. | Metadata mismatch |
| Remove old vectors | Delete specific vectors, only after replacements are verified and you approve. | Superseded, duplicate, orphan and wrong-tenant vectors |
| Needs a human | There is no automatic repair. | Orphan manifest rows and whole-collection findings |

A plan also estimates the work and cost, and compares it with re-embedding everything. Only open issues about a specific document can go into a plan, because whole-collection findings are not document repairs.

A plan moves through these statuses: **Draft** (created), **Triggered** (sent to your worker), **Partial** or **Failed** (verification found documents still wrong), **Cleanup pending** (replacements verified, old vectors waiting for your approval), **Cleanup triggered** (removal requested) and **Completed**.

**Example.** Ten documents have Missing embeddings or Stale document version issues. You create one plan. It lists ten documents with Full reindex, the chunks to regenerate, the estimated tokens and cost, and the saving compared with re-embedding the whole corpus.

**Where you see it.** The **Repair plans** tab of Integrity Issues ([Repair plans](08-repair-plans.md)).

### Signed webhook

**What it is.** RAGGuard never changes your systems. To get a repair done, it sends a request to a web address you control, which is your own worker (the **Repair worker** group in [Integrations](12-integrations.md)). "Signed" means the request carries a signature that proves it came from RAGGuard and was not altered.

The signature is an HMAC-SHA256 of the text \`<timestamp>.<exact request body>\`, made with a **Signing secret** that only you and RAGGuard know. It travels in the headers \`X-Ragi-Signature\`, \`X-Ragi-Timestamp\`, \`X-Ragi-Event\` and \`X-Ragi-Delivery\`. Your worker should reject a request whose signature is wrong or whose timestamp is more than about five minutes old. RAGGuard sends nothing at all until a signing secret is set.

Your worker can also call RAGGuard back when it is done. That call is signed with the same secret, and RAGGuard answers it by starting a verification.

Alerts are different: the **Alerts** webhook is an ordinary Slack-compatible message and is not signed.

**Example.** You press **Trigger repair**. RAGGuard sends your worker a signed request naming ten documents. Your worker re-reads them from S3, creates new embeddings, stores them and updates the manifest, then calls back. RAGGuard runs a verify audit to check the real index.

**Where you see it.** [Repair plans](08-repair-plans.md) (**View payload** shows the exact body) and [Integrations](12-integrations.md).

### Cleanup

**What it is.** The removal of vectors that should no longer be searchable: superseded old versions, duplicates, orphans and wrong-tenant vectors. It is the only step that deletes anything, and RAGGuard still does not delete: it hands your worker a second signed request with the exact point ids to remove.

Cleanup is deliberately slow and safe:

- It starts only after the replacement vectors passed verification.
- With the default **Vector removal** setting, \`manual\`, a person must press **Approve cleanup**. With \`auto\`, the request is sent right after verification.
- The list of ids is recalculated from the live index at that moment, not copied from when the plan was made.
- One request carries at most 5,000 point ids per collection.
- Orphan documents have nothing to re-embed, so after one verification they wait for cleanup right away.

**Example.** After a re-embed, the new vectors for a policy are fresh, and 7 old vectors still answer queries. You press **Approve cleanup**. A confirmation says how many vectors will be removed and that it cannot be undone. Your worker deletes exactly those 7.

**Where you see it.** **Approve cleanup** and the status **Cleanup pending** in [Repair plans](08-repair-plans.md).

### Blast radius

**What it is.** A what-if analysis: how much would be affected, and what would fixing it cost? It answers for three situations:

| Scenario | The question it answers |
|---|---|
| **Open issues** | Which documents are affected by everything wrong right now? |
| **Pipeline change** | If I move to a new parser, chunker or embedding model, which documents are built differently? |
| **Ingestion failure** | If my pipeline failed between two times, which documents did it touch? |

The result lists documents and tenants affected, collections involved, the estimated work and cost, and, when you have sent RAGGuard a retrieval log, which of the last 14 days' queries touched those documents. Only document ids and a hash of each query are kept, never the query text.

**Example.** You plan to switch embedding models. The **Pipeline change** scenario shows which documents were built with the old model, in which tenants, and what re-embedding them would cost.

**Where you see it.** The **Impact analysis** tab ([Impact analysis](09-impact-analysis.md)).

---

## Accounts and access

### Workspace

**What it is.** Your private area in RAGGuard: your connections, audits, issues, plans, alerts and API keys. In hosted mode, creating an account creates one workspace, named after the first part of your email address, for example "alice's workspace". Everything RAGGuard stores is tagged with the workspace, and one workspace can never read another's data. There is one workspace per account: there are no teams or roles yet, and the **Team** tab in Settings is marked **Not available yet**.

On a single-user server there is one implicit workspace shared by everyone who can reach the server.

**Where you see it.** The environment card at the bottom of the sidebar, the account menu, and **Settings > General**.

### Server modes and demo data

RAGGuard can run in three modes. The operator of the server chooses the mode, not you.

| Mode | Who it is for | Sign-in | Where connections come from |
|---|---|---|---|
| **Hosted** (called \`app\` in the code) | Many users, each with a private workspace | Email and password | What each user enters in **Data Sources** |
| **Live** (single-user) | One team and one set of systems | None, or a shared API key | The server's environment variables |
| **Demo** (single-user) | Exploring the product | None | A built-in synthetic knowledge base |

**Demo data** is that built-in synthetic knowledge base: invented documents in several tenants with faults put in on purpose, such as documents that were never embedded, stale versions and deleted documents that are still searchable. On a demo server a banner says "Demo data" on every page and the environment card shows **DEMO**. Nothing on a demo server comes from your own systems. The screenshots and the video that accompany this guide were made against a test workspace that also holds synthetic documents with injected faults, so your numbers will differ.

In single-user modes, **Data Sources**, **Integrations**, **Alerts** and **Settings** show the connections read-only, because the server's environment owns them.

### Read-only access

**What it means.** RAGGuard only reads from your three systems. It never writes, updates or deletes in them.

| System | What RAGGuard does |
|---|---|
| S3 | Lists objects and reads their metadata (the \`HEAD\` request). It downloads an object only when **Content hash** is \`compute\`, and then discards it. On AWS the key needs \`s3:ListBucket\` on the bucket and \`s3:GetObject\` on its objects, because AWS authorises the metadata request with \`GetObject\`. |
| PostgreSQL | Runs queries inside a read-only transaction, with a 45-second limit per statement. Use a database role that can only \`SELECT\`. The connection test warns you if your role could write. |
| Qdrant | Scrolls, retrieves and searches. Nothing is written or deleted. Use a read-capable key. |

In hosted mode RAGGuard also refuses addresses on private networks and on localhost, so the service cannot be pointed at your internal systems by mistake. The secrets you enter are encrypted before they are stored, are used only to read your systems, and are never shown again.

### API key

"API key" means three different things in RAGGuard. Which one you need depends on what you are doing.

| Kind | What it is | Where you meet it |
|---|---|---|
| **RAGGuard API key** | A token starting with \`ragi_\` that you create for scripts, CI jobs and schedulers. It is sent as \`Authorization: Bearer <key>\`, works only inside its own workspace, and can run audits and read results, but cannot read settings, create keys or change passwords. It is shown once. Only a hash is stored. You can have up to 20 and revoke any of them at any time. | **Integrations > API keys** ([Integrations](12-integrations.md)) |
| **Server API key** | A shared key that the operator of a single-user server can require before anyone uses it. The browser keeps it in memory only. | The **API key required** screen ([Sign in and find your way around](03-interface-and-sign-in.md)) |
| **Keys for your own systems** | The S3 access key and secret, and the Qdrant API key. They let RAGGuard read your systems. | The forms in **Data Sources** ([Connect your data sources](04-data-sources.md)) |

---

## Related chapters

- [Getting started](01-getting-started.md): what RAGGuard is and what you need before you begin
- [Sign in and find your way around](03-interface-and-sign-in.md): the frame around every page
- [Integrity issues](07-integrity-issues.md): each of the 11 issue types in depth
- [Isolation](20-isolation.md): whether your tenants are kept apart
- [Repair plans](08-repair-plans.md): the plan, trigger, verify and cleanup steps
- [Reference: every value](17-reference.md): every status, label and setting in one place
- [Troubleshooting](18-troubleshooting.md): what to do when something does not look right
`;export{e as default};
