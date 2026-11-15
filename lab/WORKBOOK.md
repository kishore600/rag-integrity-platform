# Practice lab workbook

Generated from `src/ragintegrity/demo/lab.py` by running the real audit on the lab, so it is always the right answer. A test fails if this file is out of date. Regenerate it with `python -m ragintegrity.demo.lab > lab/WORKBOOK.md`.

## Lab A: the 30 documents

30 documents: 27 generated ones across three tenants (acme, globex, initech) plus 3 ID-practice documents. Two of the generated documents are deleted from S3 on purpose (they are the leftovers), so S3 itself holds 28 files. 13 kinds of fault are planted, one document each. Run a full audit and compare with this table.

| # | Document | What was planted | What RAGGuard should show | What users notice | The fix |
|---|---|---|---|---|---|
| 1 | `initech/policies/alpha-026.md` | **Never embedded**: The file is in S3, but the pipeline never processed it: no manifest row and nothing in Qdrant. | Missing embeddings (high) | Nobody can ever find this document. No error is shown. | Re-run the document through the pipeline (a repair plan sends it to your worker). |
| 2 | `initech/policies/zenith-019.md` | **Pipeline said success, nothing is indexed**: The manifest says `success` with N chunks indexed, but Qdrant holds nothing for the document. | Missing embeddings (critical) | Dashboards look green, yet the document is invisible. This is the most dangerous case. | Re-index it, and find out why the pipeline ticks success before the vectors are written. |
| 3 | `initech/runbooks/omega-021.md` | **Out of date**: The file changed in S3 after it was indexed; the manifest and the vectors describe the old version. | Stale document version (high) | The chatbot answers from an old version of the document. | Re-index the document so the vectors match the current file. |
| 4 | `acme/contracts/delta-008.md` | **Deleted file, vectors and manifest row remain**: The file was deleted from S3, but its vectors and its manifest row are still there. | Orphan vectors (critical) | The chatbot can still quote a document that no longer exists. | Remove the leftover vectors (an approved cleanup), then the manifest row. |
| 5 | `acme/product/zenith-007.md` | **Deleted file, vectors remain**: The file was deleted from S3 and its manifest row is gone, but the vectors are still in Qdrant. | Orphan vectors (critical) | Deleted content stays searchable. | Remove the leftover vectors (an approved cleanup). |
| 6 | `acme/product/sigma-004.md` | **Half indexed**: The ingest worker died half way: only some of the document's chunks are in Qdrant, while the manifest claims all of them. | Partial index (critical) | Answers about the missing parts are wrong or empty. | Re-index just the missing chunks. |
| 7 | `acme/policies/omega-006.md` | **Duplicate chunks**: A retried job inserted two chunks a second time with new point ids. | Duplicate chunks (medium) | The same passage is returned twice and crowds out other results. | Remove the extra copies (an approved cleanup). |
| 8 | `acme/policies/delta-001.md` | **Permissions disagree**: The manifest's permission hash differs from the one on the vectors. | Metadata mismatch (high) | People may see (or be blocked from) a document they should not (or should). | Fix the permission metadata; no re-embedding is needed. |
| 9 | `globex/policies/sigma-018.md` | **Chunk count disagrees**: The manifest says one more chunk was indexed than Qdrant really holds. | Metadata mismatch (medium) | Usually nothing visible, but the records cannot be trusted. | Correct the manifest (or re-index if chunks are really missing). |
| 10 | `acme/product/sigma-003.md` | **Built with an old pipeline**: The document was indexed with an old parser, chunking and embedding model; the target pipeline is newer. | Pipeline drift (high) | Search quality is inconsistent, and old and new vectors cannot be compared. | Re-index with the current pipeline. |
| 11 | `initech/support/zenith-024.md` | **Old version still searchable**: The document was updated and re-indexed correctly, but the previous version's vectors were never removed. | Superseded vectors active (high) | Old and new text both appear in answers. | After the new version is verified, remove the old vectors (an approved cleanup). |
| 12 | `acme/support/alpha-005.md` | **Empty vectors**: Two of the document's points have an all-zero vector, so they can never match a query. | Empty embeddings (high) | Parts of the document can never be found. | Re-index the document. |
| 13 | `acme/contracts/sigma-023.md` | **Another customer's label**: The vectors of one document carry a different tenant's label. The real document then looks missing. | Tenant mismatch (critical) | Content can be returned to the wrong customer: a data leak. | Re-index under the right tenant, then remove the wrongly labelled vectors. |
| 14 | `initech/contracts/sigma-023.md` | The real document of the tenant-mismatch fault above | Missing embeddings (critical) | It looks missing because its vectors carry another tenant's label. | Fixed together with the tenant mismatch above. |

The other **14 generated documents** are healthy: `acme/policies/bravo-002.md`, `acme/support/zenith-009.md`, `globex/contracts/delta-013.md`, `globex/policies/sigma-010.md`, `globex/product/bravo-011.md`, `globex/product/sigma-014.md`, and so on.

### What a full audit of the 27 generated documents should say

- 28 entries compared (the wrongly labelled vectors count as one extra), 14 findings, health score 50.0%.
- Isolation page: overall **leak** (rows 13 and 14 are the tenant mismatch).
- **With the 3 practice documents added (what you will see in the app):** 31 entries, 14 findings, health 54.8%, plus one duplicate-manifest-ID warning.

### The ID practice documents (added to Lab A as well)

| Document | What was planted | What RAGGuard should show |
|---|---|---|
| `acme/20001` | The ID is stored in Qdrant as a whole number. | **Healthy.** The same ID written as a number, a decimal or text is one ID. Setup check: shows how each system stores IDs. |
| `acme/20002` | The ID is stored in Qdrant as a decimal (as a spreadsheet or JSON library would write it). | **Healthy.** The same ID written as a number, a decimal or text is one ID. Setup check: shows how each system stores IDs. |
| `acme/20003` | The ID is stored in Qdrant as text. | **Healthy.** The same ID written as a number, a decimal or text is one ID. Setup check: shows how each system stores IDs. |
| `acme/policies/bravo-002.md` | Its manifest row exists twice (an exact copy). | The audit result carries a **duplicate manifest ID** warning (Overview and Audit History; the setup check too). The document itself stays healthy. |

## Lab B: mini bills (practise the real sign-up and settings flow)

A miniature of the real setup: files at `bills/<bill>/<document>.pdf` in the bucket `bills-lab`, a `bill_documents` table with a true/false `is_indexed`, and a `bill_chunks` collection whose pieces only know their bill (`source_id`). Open http://localhost:8001, **create an account** (any email and password, they stay on your computer) and type these into the pages, exactly as you would for a real customer. The addresses are the ones the app inside Docker uses to reach the other containers.

| Page | Field | Value |
|---|---|---|
| Data Sources, Amazon S3 | Bucket / Key prefix / Region | `bills-lab` / `bills/` / `us-east-1` (**keep the slash at the end of the prefix**: without it the key pattern matches nothing, the audit sees 0 documents and shows "0 issues") |
| | Custom endpoint | `http://s3:5000` |
| | Access key ID / Secret access key | `test` / `test` (the lab's fake S3 accepts any keys) |
| | Content hash | `etag` |
| | Key pattern (regex) | `^(?P<document_id>[^/]+)/(?P=document_id)\.pdf$` |
| | Look up files from the manifest | on |
| Data Sources, PostgreSQL | Connection string | `postgresql://postgres:postgres@postgres:5432/postgres` |
| | Schema / Document table | `public` / `bill_documents` |
| | Column map (JSON) | `{"document_id":"external_doc_id","source_uri":"s3_url","processing_status":"is_indexed"}` |
| Data Sources, Qdrant | URL / Collections | `http://qdrant:6333` / `bill_chunks` |
| | Payload field map (JSON) | `{"document_id":"source_id"}` |
| Settings, Policy | Grace period (minutes) | `0` (the files were created seconds ago; with the default 10 two documents show as *pending*) |
| | Required payload fields | `document_id` |
| | Only audit documents found in the source (S3) | on |
| Integrations, Repair webhook | Webhook URL / Signing secret | `http://worker-bills:9000/ragi-webhook` / `local-lab-secret` (only needed for the repair practice at the end) |
| Integrations, Email | SMTP server / Port / Connection security / From address | `mail` / `1025` / `none` / `ragguard@lab.local` (leave Username and Password empty; only needed for the email practice at the end) |

Save each group, press **Check setup** on Data Sources, then **Run audit**. What each document should give:

| Bill | Document | Type | Planted | With these settings |
|---|---|---|---|---|
| 2300001 | 2300001 | prefiled | Healthy: file, row marked indexed, 4 pieces in Qdrant. | Healthy |
| 2300002 | 2300002 | prefiled | Healthy: 6 pieces. | Healthy |
| 2300003 | 2300003 | prefiled | Healthy, but Qdrant stores this bill's ID as a whole number (numbers versus text). | Healthy |
| 2300004 | 2300004 | prefiled | The row says indexed, but Qdrant has nothing: a false success. | **Critical: Missing embeddings** |
| 2300005 | 2300005 | prefiled | Never indexed: the row says not indexed, Qdrant has nothing. | **High: Missing embeddings** |
| 2200001 | 3300001 | Introduced | One of two documents of bill 2200001; Qdrant only knows the bill. | outside the key pattern (folder differs from file name), not audited |
| 2200001 | 3300002 | Fiscal Note | The other document of bill 2200001 (its pieces cannot be told apart from the first). | outside the key pattern (folder differs from file name), not audited |
| 2200002 | 3300003 | Introduced | A bill with nothing in Qdrant at all. | outside the key pattern (folder differs from file name), not audited |
| 9000001 | 9000001 | (file only) | A file with 2 pieces in Qdrant but no table row. | Not seen while *Look up files from the manifest* is on (the blind spot). |
| 8000001 | | (pieces only) | 3 pieces in Qdrant for a bill with no file and no row. | Ignored while *Only audit documents found in the source* is on. |

Expected audit with these settings: **5 documents compared, 2 findings** (one critical, one high), health 60%. The Isolation page says *limited* (the source-only switch hides wrong-tenant vectors).

### Exercises: change one setting, run the audit, read the difference

| # | Change | What you should see | What it teaches |
|---|---|---|---|
| 1 | Turn **off** *Look up files from the manifest* | 6 documents, 3 findings. The new one is `9000001`: **Metadata mismatch (medium)**, vectors but no table row. | Without the lookup the app lists the bucket and finds files the table does not know (it also gets slow on a huge bucket). |
| 2 | Turn **off** *Only audit documents found in the source* | 11 documents, 8 findings, health 27%: orphan vectors for bill `2200001`, orphan-row warnings for `3300001` to `3300003`, orphan vectors for `8000001` and `9000001` (all the orphan vectors are **critical**: the search test finds their pieces at rank 1), plus the two real ones. | Why the switch exists: the key pattern skips most documents, so everything the pattern skips looks like a leftover. On a big shared index the audit would also read every piece and run out of time. |
| 3 | Turn **off both** switches | 11 documents, 8 findings. Same as above, except `9000001` is now a **Metadata mismatch (medium)**. | The two switches decide which of the two directions (file to shelf, shelf to file) the audit checks. |
| 4 | Per bill: Key pattern `^(?P<document_id>[^/]+)/[^/]+\.pdf$` and Column map `document_id` set to `external_bill_id` | 7 documents, 3 findings (bill `2200002` **critical**, `2300004` critical, `2300005` high), a **duplicate manifest ID** warning, health 57%. | Bill-level checking works, but bill `2200001` (two documents) would stay healthy even if only one of them were indexed, because Qdrant only knows the bill. |

### Repair practice: fix the two broken bills

Put the settings back as in the first table (and save the repair webhook from its last row), run the audit, then:

1. **Integrity Issues**: tick both open issues (`2300004`, `2300005`) and press **Create repair plan**.
2. Open the plan and press **Trigger repair**. RAGGuard sends a signed request to the Lab B worker (`worker-bills`).
3. Press **Verify now**. The worker found each file from its address in the plan, wrote its pieces into `bill_chunks` and marked the row `is_indexed` in `bill_documents`, so both bills show **Completed**.
4. **Run audit** again: **5 documents compared, 0 findings, health 100%**.

Lab A has its own worker, so a repair there never touches Lab B (and the other way round). A worker is *your* pipeline: it must know where your files live and how your vectors and table are laid out, which is why the two labs need two workers.

### Bulk repair and email practice

Lab A is already set up for email (Lab B needs the **Email** row of the settings table). Every email lands in the lab's mail catcher, **http://localhost:8025**, and goes nowhere else.

1. **Integrity Issues**, then **Repair all open issues**. Choose *All severities*. The box shows the documents, chunks, cost and vectors to remove before anything happens.
2. Turn on **Also email the plan**, type any address (for example `me@example.com`) and a note, and press **Create and send**. One plan holds every document and one signed request carries them all.
3. Open http://localhost:8025. The email has a summary and a table, a link back to the plan, a **CSV** with every document and the exact JSON the worker received.
4. In the plan, **Verify now** (or let the worker's callback do it), then **Approve cleanup** for the leftovers, then **Run audit**: Lab A ends at **28 documents, 0 findings, health 100%**.
5. Any plan also has **Email plan** and **Download CSV**. Try them on a plan that is still a draft.

