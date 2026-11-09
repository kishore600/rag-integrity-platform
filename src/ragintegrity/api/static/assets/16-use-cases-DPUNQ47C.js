const e=`# Practical use cases

This chapter gives ten situations you are likely to meet, each as a short recipe: the goal, the exact steps in the product, and how to read the result. Use it when you know what you want to achieve but not which pages to open. Where a step depends on something the product marks **Not available yet**, the step says so and gives a workaround. The full walk from sign-up to a verified fix is in [End-to-end journey](15-end-to-end-journey.md), and every value you will see is explained in [Reference: every value](17-reference.md).

New words in this chapter (audit, issue, manifest, tenant, probe) are explained in [Concepts you need](02-concepts.md).

**On this page**

- [Which use case do I need?](#which-use-case-do-i-need)
- [Use case 1: A first-time baseline of an existing RAG system](#use-case-1-a-first-time-baseline-of-an-existing-rag-system)
- [Use case 2: A nightly or CI audit through the API](#use-case-2-a-nightly-or-ci-audit-through-the-api)
- [Use case 3: After changing the embedding model](#use-case-3-after-changing-the-embedding-model)
- [Use case 4: After an ingestion outage](#use-case-4-after-an-ingestion-outage)
- [Use case 5: Investigating a user report of a wrong answer](#use-case-5-investigating-a-user-report-of-a-wrong-answer)
- [Use case 6: Responding to a tenant mismatch](#use-case-6-responding-to-a-tenant-mismatch)
- [Use case 7: Cleaning up after documents were deleted](#use-case-7-cleaning-up-after-documents-were-deleted)
- [Use case 8: Proving to a manager that the index is healthy](#use-case-8-proving-to-a-manager-that-the-index-is-healthy)
- [Use case 9: Onboarding a second tenant or collection](#use-case-9-onboarding-a-second-tenant-or-collection)
- [Use case 10: Reducing re-embedding cost](#use-case-10-reducing-re-embedding-cost)
- [Related chapters](#related-chapters)

## Which use case do I need?

| You want to | Use case | Main pages |
|---|---|---|
| Find out where an index that is already running really stands | 1 | Data sources, Reconciliation, Overview |
| Check the index every night, or on every deployment, and fail a job when something serious is open | 2 | Integrations (API keys), the API |
| Move to a new embedding model, chunk size or parser | 3 | Integrity issues (Impact analysis, Repair plans), Settings |
| Recover from a period when ingestion was failing | 4 | Integrity issues (Impact analysis, Issues, Repair plans) |
| Find out why a user got a wrong or missing answer | 5 | Documents |
| React to vectors tagged with the wrong tenant | 6 | Integrity issues, Isolation, Documents |
| Remove vectors of documents that were deleted | 7 | Integrity issues, Repair plans |
| Show someone that the index is healthy | 8 | Overview, Reconciliation (Export report), Audit history |
| Add another customer or another collection | 9 | Data sources, Settings, Reconciliation |
| Keep the cost of fixing the index down | 10 | Integrity issues (Repair plans, Impact analysis), Settings (Policy) |

## Use case 1: A first-time baseline of an existing RAG system

**Goal:** learn where an index that has been running for a while really stands, separate real problems from set-up noise, and keep a record of the starting point.

**Before you start:** have your S3 read-only key, the manifest connection string and the Qdrant URL ready. Remember the hash rule: the SHA-256 that RAGGuard reads from S3 must be the same value your pipeline records as \`source_hash\`.

**Steps**

1. Sign up and connect the three systems exactly as in Steps 1 and 2 of the [End-to-end journey](15-end-to-end-journey.md). On **Data sources**, use **Test connection** in every dialog and read the amber lines before you save. They predict weak spots:
   - **Content hashes** amber (S3): objects carry no SHA-256, so stale documents will be hard to detect.
   - **Columns used for checks** amber (manifest): some of \`source_hash\`, \`processing_status\`, \`expected_chunk_count\`, \`indexed_chunk_count\` are not mapped.
   - **Payload of NAME** amber (Qdrant): sampled vectors lack \`source_hash\`.
2. Leave **Settings**, **Pipeline** empty for the first audit. A wrong target would make every document look drifted. If your manifest or index holds more than your bucket covers (for example one Qdrant collection shared with other products), switch on **Only audit documents found in the source (S3)** on the **Policy** tab.
3. Open **Reconciliation** and click **Run full audit**.
4. Open **Overview**. Note the **Health score**, **Open issues**, **Issues by type**, **Document status** and **Tenant health**.
5. Open **Reconciliation** and compare **Source documents**, **Manifest rows** and **Index vectors**.
6. Sort noise from real problems (see the table below). To check one document in detail, open **Documents**, click the document, open the **Chunks** tab and click **Inspect live**.
7. Fix any set-up problem you found, then run another full audit. Repeat until the remaining issues look like real problems.
8. Optional: now fill in **Settings**, **Pipeline** with the pipeline you expect, and audit again to see real drift.
9. Record the baseline: on **Reconciliation** click **Export report** and choose **Markdown**. Write down the health score and the open issue counts.

**How to read the result**

| What you see | What it usually means | What to do |
|---|---|---|
| Almost every document has the same issue, such as **Stale document version** | A set-up mismatch, not a thousand real problems. The hash RAGGuard reads from S3 is not the one your pipeline records. | Open one document, **Inspect live**, and compare the source hash with the manifest and payload hashes. Align them, then re-audit. |
| Many **Missing embeddings** and, with similar names, many **Orphan vectors** | The document id is written differently in different systems (for example \`leave.pdf\` in Qdrant but \`policies/leave.pdf\` in S3) | Check **Key prefix** and **Key pattern**, and what your pipeline writes as \`document_id\`. See [Troubleshooting](18-troubleshooting.md), "Documents shown as Failed, Missing or orphaned unexpectedly". |
| Many **Pipeline drift** | You filled in the target pipeline and it does not match what your pipeline records | Correct the target, or the pipeline |
| A few critical issues titled "(pipeline claims success)" | Real. The pipeline said it succeeded but the index disagrees. | Triage them first (Use case 5 shows how to inspect one) |
| No issues at all | Either a healthy index, or a configuration that hides problems | Read "Zero issues when you expect some" in [Troubleshooting](18-troubleshooting.md) |

**If something does not work:** see [Troubleshooting](18-troubleshooting.md).

## Use case 2: A nightly or CI audit through the API

**Goal:** audit automatically on a schedule or on every deployment, and fail a job when open critical issues exist.

**What you need:** an API key (**Integrations**, **API keys**, **Create API key**, see Step 16 of the [End-to-end journey](15-end-to-end-journey.md)) and the address of your RAGGuard site. A key works only inside your workspace.

**The endpoints used** (all real, all accept \`Authorization: Bearer <key>\`):

| Call | Purpose |
|---|---|
| \`POST /api/audits\` with body \`{"wait": true}\` | Start a full audit and wait for it to finish. The answer is \`{"run_id": "...", "status": "completed", "stats": {...}}\`. Add \`"tenant": "acme"\` to audit only one tenant. |
| \`GET /api/issues?status=open&severity=critical&limit=1\` | The answer's \`total\` is the number of open critical issues. |
| \`GET /api/overview\` | Health, counts by severity, and the latest runs, if you want more numbers. |

Some points to know:

- Send the header \`Content-Type: application/json\` with the \`POST\`.
- On a hosted server one audit has a time budget of 270 seconds, and the server function itself stops at 300 seconds. Allow your job to wait about five and a half minutes (the examples use \`--max-time 330\`).
- Only one audit can run at a time per workspace. If someone clicks **Run audit** while your job runs, the job gets a \`409\` ("An audit is already running."). Run it again later.
- There is no scheduler inside the hosted app and no scheduling screen. The scheduler is yours: GitHub Actions, cron, or any CI system.

**A GitHub Actions workflow** (store the key as a repository secret named \`RAGGUARD_API_KEY\`):

\`\`\`yaml
name: RAG integrity audit
on:
  schedule:
    - cron: "0 2 * * *"      # every night at 02:00 UTC
  workflow_dispatch:         # also lets you run it by hand
jobs:
  audit:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    env:
      RAGGUARD_URL: https://your-ragguard-address
      RAGGUARD_KEY: \${{ secrets.RAGGUARD_API_KEY }}
    steps:
      - name: Run a full audit and wait for it
        run: |
          curl -sS --fail-with-body --max-time 330 -X POST "$RAGGUARD_URL/api/audits" \\
            -H "Authorization: Bearer $RAGGUARD_KEY" \\
            -H "Content-Type: application/json" \\
            -d '{"wait": true}' -o audit.json || { cat audit.json; exit 1; }
          echo "Health score: $(jq '.stats.health_score' audit.json)%"
      - name: Fail when critical issues are open
        run: |
          curl -sS --fail-with-body --max-time 60 \\
            "$RAGGUARD_URL/api/issues?status=open&severity=critical&limit=1" \\
            -H "Authorization: Bearer $RAGGUARD_KEY" -o critical.json || { cat critical.json; exit 1; }
          critical=$(jq '.total' critical.json)
          echo "Open critical issues: $critical"
          if [ "$critical" -gt 0 ]; then exit 1; fi
\`\`\`

The answers are saved to files first, and the step stops if the call itself fails, so a failed call can never be mistaken for "no critical issues". \`--fail-with-body\` needs curl 7.76 or newer, and \`jq\` is a small tool for reading JSON; both are present on GitHub's standard Ubuntu runners.

**A cron example** (a small script plus one crontab line; keep the key in a file only you can read):

\`\`\`bash
#!/usr/bin/env bash
# /opt/ragguard/nightly-audit.sh
set -euo pipefail
source /etc/ragguard.env      # contains: RAGGUARD_URL=...  and  RAGGUARD_KEY=ragi_...

curl -sS --fail-with-body --max-time 330 -X POST "$RAGGUARD_URL/api/audits" \\
  -H "Authorization: Bearer $RAGGUARD_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"wait": true}' -o /tmp/ragguard-audit.json || { cat /tmp/ragguard-audit.json >&2; exit 1; }

curl -sS --fail-with-body --max-time 60 \\
  "$RAGGUARD_URL/api/issues?status=open&severity=critical&limit=1" \\
  -H "Authorization: Bearer $RAGGUARD_KEY" -o /tmp/ragguard-critical.json || { cat /tmp/ragguard-critical.json >&2; exit 1; }

critical=$(jq '.total' /tmp/ragguard-critical.json)
if [ "$critical" -gt 0 ]; then
  echo "RAGGuard: $critical open critical issue(s)" >&2
  exit 1
fi
echo "RAGGuard: no open critical issues"
\`\`\`

\`\`\`text
# crontab -e   (every night at 02:15; cron mails or logs the output of a failing run)
15 2 * * * /opt/ragguard/nightly-audit.sh >> /var/log/ragguard-audit.log 2>&1
\`\`\`

To fail on "critical or high" instead, replace the second call with \`GET /api/overview\` and compute \`jq '.issues.by_severity.critical + .issues.by_severity.high'\`.

**How to read the result**

- The job turns red when the audit itself fails (the job prints the server's message: a \`502\` explains which of your systems refused, a \`504\` means the time budget ran out, a \`401\` means the key is wrong), or when critical issues are open.
- Ignored issues do not count, because \`status=open\` excludes them.
- The audit appears in **Audit history** with the trigger **Api**.

**Not available yet:** email alerts, and digest and quiet hours. **Workaround:** add an alert webhook on the **Alerts** page (Step 15 of the journey) so new issues also reach Slack, or make your CI system send the failure message. The Slack, Jira and PagerDuty integrations are marked **Not available yet** on **Integrations**.

**If something does not work:** see "API key problems" in [Troubleshooting](18-troubleshooting.md).

## Use case 3: After changing the embedding model

**Goal:** find out, before you roll out a new embedding model (or a new chunk size or parser), how many documents must be re-processed and what that costs. Afterwards, confirm that the index matches the new model.

**Steps, before the rollout**

1. Open **Integrity issues** and click the **Impact analysis** tab.
2. Under **Scenario** choose **Pipeline change**.
3. Fill in the pipeline you are moving to. The fields are **Parser version**, **Chunking version**, **Embedding model**, **Embedding model version**, **Chunk size (tokens)** and **Chunk overlap (tokens)**. Each shows "Current target: ..." if your **Settings**, **Pipeline** has a value. You must fill in at least one, or the page says "Enter at least one setting of the pipeline you want to analyze."
4. Click **Analyze impact**. RAGGuard reads your latest audit results and changes nothing.

**How to read the result**

| Part | Meaning |
|---|---|
| **Documents affected** ("N of M", with a percentage) | Documents that exist in the source and either record a different value for a field you entered, or record no value for it |
| **Confirmed** ("Index known to differ from the proposed pipeline") | Documents whose recorded setup differs for sure |
| Rows marked **Possible** in the **Affected documents** list | Documents where RAGGuard has no recorded value to compare, so it cannot be sure. Make your pipeline record its settings to remove the doubt. |
| **Chunks to regenerate**, **Estimated cost**, and the hint "Full reindex: ..." | The work and cost of re-embedding the affected documents, and of re-embedding everything. The small text under the cards states the assumptions (tokens per chunk and price). |
| **Savings vs full reindex** | Shown when it can be computed |
| **Tenants affected** | Which customers are touched, as affected out of total |
| **Issues by type** and **Collections affected** | Open issues on those documents, and which Qdrant collections hold them |
| **Query impact** | How many recent searches returned an affected document. It needs a retrieval log: until you send one it says "No query log has been ingested yet". See Use case 4 for how to send one. |

**Steps, during and after the rollout**

5. When your pipeline is ready to write with the new model, set the same values in **Settings**, **Pipeline** (**Embedding model**, **Embedding model version**, **Embedding dimensions**, and so on) and click **Save**. From the next audit, every document whose vectors were built with the old model is reported as **Pipeline drift**, severity high when the embedding model, its version or the dimensions differ. Set the target when you are ready to repair, not earlier, or the whole corpus appears as drifted at once.
6. If the new model produces vectors of a different size, a collection cannot hold both. If you set **Embedding dimensions** and a collection's vector size differs, RAGGuard raises a **Critical** collection-level finding, "Collection vector size does not match the target embedding model". Create a new collection for the new model, and add its name under **Collections** on the Qdrant card (**Edit**, then **Save**).
7. Run a full audit, then go to **Repair plans**, **Create plan from recommendations**, **Trigger repair**, **Verify now**, and **Approve cleanup** (Steps 9 to 13 of the [End-to-end journey](15-end-to-end-journey.md)). Your worker must embed with the new model.
8. While old and new vectors of one document exist together, expect **Superseded vectors active** (medium). It disappears after cleanup.

**If something does not work:** see "Too many issues" in [Troubleshooting](18-troubleshooting.md).

## Use case 4: After an ingestion outage

**Goal:** find every document that your pipeline touched while it was failing, check which are really broken, and repair them.

**Steps**

1. Note when the outage started and ended.
2. Run a full audit so the results are current (**Reconciliation**, **Run full audit**). Documents changed within the grace period (default 10 minutes) are shown as **Pending**, not broken, so wait for ingestion to settle first.
3. Open **Integrity issues**, **Impact analysis**, choose **Ingestion failure**.
4. Fill in **Started at** (required, your local time) and **Ended at** (leave it empty for "until now"). Click **Analyze impact**.
5. Read the result. The affected documents are those whose manifest **updated at** time falls inside the window, so the manifest's \`updated_at\` column must exist and be mapped. **Confirmed** means the document already has an open issue; the rest are marked **Possible** (touched during the window, no issue found, probably fine).
6. Go to the **Issues** tab and look at **Missing embeddings**, **Partial index** and **Stale document version**. Titles that end "(pipeline claims success)" are the dangerous ones: the pipeline said it worked. For a job that was stuck, the issue text says the pipeline has had the document in a status such as "processing" since a given time.
7. Go to **Repair plans**, click **Create plan from recommendations**, and carry it out (Steps 9 to 13 of the journey).
8. Optional: measure the effect on real searches. Retrieval logs are sent through the API, because there is no upload screen. Send one call with your API key:

\`\`\`bash
curl -X POST "https://your-ragguard-address/api/query-log" \\
  -H "Authorization: Bearer ragi_xxxxxxxx" \\
  -H "Content-Type: application/json" \\
  -d '{"queries": [
        {"tenant_id": "acme", "query_text": "how many leave days", "retrieved_doc_ids": ["policies/leave.md"], "ts": "2026-11-08T10:15:00Z"}
      ]}'
\`\`\`

   The answer is \`{"ingested": N}\`. Only the document ids and a hash of the query are kept, never the text of the query. A call takes up to 5,000 rows. The **Query impact** card counts searches from the last 14 days.

**How to read the result:** **Documents affected** versus **Confirmed** tells you how much of the window did real damage. **Query impact** tells you how many real searches returned an affected document, and **Most requested affected documents** tells you which to fix first.

**If something does not work:** if the analysis shows no documents, the manifest \`updated_at\` is probably not mapped, or the window is wrong. See [Troubleshooting](18-troubleshooting.md).

## Use case 5: Investigating a user report of a wrong answer

**Goal:** a user got a wrong, outdated or missing answer. Find out whether the index is at fault, and why.

RAGGuard never stores the contents of your documents or the text of user questions, so you search by the document's name or id, not by the words of the answer.

**Steps**

1. Work out which document should have answered, or which one did.
2. Press \`/\` (or click the search box at the top), type the name, and choose **Search Documents for "..."**. The **Documents** page opens filtered to that text. You can also open **Documents** and type in **Search by document id**.
3. Click the document's row. A panel opens on the **Overview** tab.
4. Read it:
   - **Status**: the embedding status (**Healthy**, **Stale**, **Missing embeddings**, **Processing**, **Failed**), the audit result, and the open issues.
   - **Where this document exists**: three boxes, **Source** (Amazon S3), **Manifest** (PostgreSQL) and **Index** (Qdrant), each **Present** or **Missing**.
   - **Details**: source hash, **Source version** and **Indexed version** (an amber triangle means the index was built from a different version), **Chunks (indexed / expected)**, **Collections**, **Manifest status** and **Last verified**.
5. The Overview shows what the last audit saw. To see the truth right now, open the **Chunks** tab and click **Inspect live**. RAGGuard reads S3, the manifest row and the Qdrant vectors at that moment, which can take a few seconds. Or click **Re-audit document** at the top of the panel to audit just this document.
6. Read the live view: **Source**, **Manifest**, **Index** (the number of vectors, and badges such as "Fresh: 5" per class), the **Chunks** table (**Chunk**, **Index**, **Class**, **Copies**, **Collection**) and **Findings from this check**.
7. Open the **Issues** tab, click an issue, and read **Evidence**, including the **Retrieval probe**, which shows whether the bad content can really be returned by a search.
8. Decide: **Create repair plan** (Steps 9 to 13 of the journey), **Ignore** with a reason, or fix the cause in your pipeline.

**How to read the result**

| What you see | Meaning for the user's wrong answer |
|---|---|
| **Index** box is **Missing** | The document is not searchable at all. The user could never get an answer from it. |
| **Source** is **Missing** but **Index** is **Present** | The document was deleted but is still searchable. The user may have been given deleted content. |
| An amber triangle between **Source version** and **Indexed version** | The index describes an older version. The answer was outdated. |
| Chunk **Class** \`stale\` next to \`fresh\` chunks | Old chunks still compete with the current ones and can outrank them |
| **Copies** above 1 | The same chunk is indexed more than once, which skews ranking |
| **Class** \`unknown\` | The payload carries no hash or version, so RAGGuard cannot tell if the chunk is current |
| **Chunks** fewer than expected | Only part of the document is searchable. The missing part is what the user asked about. |
| **Manifest** is **Missing** | The pipeline has no record of the document (it was never picked up, or the id differs) |
| "Document not found" | RAGGuard has no record of the document in this workspace. Check your **Key prefix** and **Key pattern**, or run an audit. |

The retrieval probe replays one affected chunk's own vector. It proves the content is searchable and at what rank, but it does not replay the user's actual question.

**If something does not work:** see [Troubleshooting](18-troubleshooting.md). More on the page itself in [Documents](10-documents.md).

## Use case 6: Responding to a tenant mismatch

**Goal:** vectors are tagged with the wrong tenant, which can leak one customer's content to another. Contain it and confirm it is gone.

A tenant is a customer or business unit whose documents must stay separate. The issue **Tenant mismatch** is always **Critical**. The **Isolation** page shows all tenants at once and which ones are affected ([Isolation](20-isolation.md)).

**Steps**

1. Open **Integrity issues**, set **Type** to **Tenant mismatch** (or click the **Critical** chip).
2. Click an issue and read the panel:
   - **What's wrong**: how many vectors are indexed under one tenant while the source document exists only under another.
   - **Expected vs actual**: for example "Vectors tagged with tenant B" against "N vectors tagged with another tenant".
   - **Evidence**: the vector count, the collections, the expected tenants, and the **Retrieval probe**, which queries the index filtered to the tenant the vectors are wrongly tagged with.
   - **Why it matters** tells you to treat it as a security incident.
3. Contain it in your own systems. RAGGuard never changes your data. Decide whether the wrongly tagged vectors should be deleted or retagged. The evidence lists the collection and a sample of point ids; **Raw evidence (JSON)** holds the full list of vectors to remove (up to 5,000 per collection).
4. If you want RAGGuard to hand the removal to your worker, use **Create repair plan**. See the limit in Use case 7 below: a plan that contains only removal work cannot be triggered in this version. Removing the vectors yourself and re-auditing always works.
5. Confirm: open the document in **Documents** and click **Re-audit document**, or run a **Scoped audit** (**Reconciliation**) for the affected tenant. The issue becomes **Resolved**, and its Timeline says "Resolved: the index now matches the source."
6. Check the other tenant too. The document may now show **Missing embeddings** there, which means its own tenant's copy was never written.
7. Prevent a repeat: look at the step in your pipeline that writes \`tenant_id\` to the payload. On **Alerts**, set **Minimum severity** to **critical** if you want alerts for critical issues only (a tenant mismatch is always critical).

**How to read the result:** a **Retrieval probe** with **Reachable** "Yes" means a search scoped to that tenant really returns the misplaced vectors. A document that is gone from the source and not found under any other tenant is not a tenant mismatch; it is an orphan (Use case 7).

**If something does not work:** see [Troubleshooting](18-troubleshooting.md).

## Use case 7: Cleaning up after documents were deleted

**Goal:** a document was deleted from S3, but its vectors are still searchable. Find them, remove them, and confirm.

**Steps**

1. Run a full audit. On **Overview**, **Document status** shows a count under **Orphaned** ("Deleted at the source, vectors remain").
2. Open **Integrity issues** and set **Type** to **Orphan vectors**. Each issue says "Vectors remain for a document that no longer exists".
3. Open one. Check that the deletion was intended. **Evidence** shows how many vectors remain, in which collections, and the **Retrieval probe**. If the probe shows the content is returned for a matching query, the severity is raised from **High** to **Critical**.
4. Remove the vectors. Choose one path:
   - **Path A, in your own tools:** delete the listed vectors (the evidence has the collection and point ids; **Raw evidence (JSON)** has the full list), and have your pipeline retire the manifest rows of the deleted documents. Then re-audit.
   - **Path B, through RAGGuard:** click **Create repair plan** (or tick several orphan issues and click **Create repair plan**, or use **Create plan from recommendations**). Then follow Steps 10 to 13 of the [End-to-end journey](15-end-to-end-journey.md): the plan goes **Triggered**, **Verify now**, **Cleanup pending**, **Approve cleanup**, **Cleanup triggered**, **Verify now**, **Completed**.
5. Confirm: run **Run full audit** again. The orphan issues are **Resolved** and the **Orphaned** count falls to zero.

**Know the limit of Path B in this version.** A plan reaches **Cleanup pending** only after a **Trigger repair** and a **Verify now**, and **Trigger repair** sends only documents that need re-processing. A plan made *only* of removal work (all orphan, duplicate, superseded or tenant-mismatch vectors, and no document to re-process) therefore answers "This plan has nothing to reprocess (cleanup only). Use approve-cleanup." and **Approve cleanup** is not offered while the plan is **Draft**. Two ways around it: use Path A, or create the plan from **Create plan from recommendations** at a time when it also contains at least one document that needs re-processing; the removal-only documents then show **Waiting for cleanup** after **Verify now** and are removed together with the rest on **Approve cleanup**. See "Cleanup not offered" in [Troubleshooting](18-troubleshooting.md).

**After the vectors are gone:** if the manifest still lists the deleted document, the next audit reports **Orphan manifest row** (low). Have your worker retire those rows as part of the cleanup.

**How to read the result:** an orphan that is **Critical** is being returned to users right now, so do it first. **Orphan vectors** versus **Tenant mismatch**: an orphan's document id exists in no tenant; a tenant mismatch's id exists in a different tenant.

**If something does not work:** see [Troubleshooting](18-troubleshooting.md).

## Use case 8: Proving to a manager that the index is healthy

**Goal:** show, with evidence, that the index agrees with the source, and that it keeps doing so.

**Steps**

1. Run a full audit now, and ideally schedule one (Use case 2) so there is a history.
2. On **Overview** show the **Health score** (green at 90% and above), **Open issues** ("None critical or high"), and **Health over time**, which needs two full audits to draw a line. **Tenant health** shows the score per customer.
3. On **Reconciliation** show the three counts side by side and the line "The manifest lists as many rows as the source has documents."
4. Click **Export report** and choose a format:
   - **Markdown**, "Readable report": a summary (documents checked, health score, open issues by severity) and a section per inconsistent document.
   - **CSV**, "One row per issue": for spreadsheets.
   - **JSON**, "Everything, for tools".
   The file is named \`rag-integrity-report\` with the matching extension. It lists only documents that have open issues, so a clean index gives a short report that says "None. The index agrees with the source." To include healthy documents too, call the API: \`GET /api/report?format=md&include_healthy=true\`.
5. For an audit trail, open **Audit history**, **Audit runs**, click a run, and use **Copy run id**. The **Activity log** shows every issue found and resolved, every repair and every audit in order.

**How to read the result honestly:** a green score with zero open issues is the goal, but two things deserve a mention. **Pending** documents count as healthy (they are still being processed), and **Ignored** issues are not counted as open. Check **Integrity issues** with **Status** set to **Ignored** so you can say what has been accepted and why.

**Not available yet:** **Team** on **Settings** ("Invite teammates and set roles"). Each account owns one workspace, so you cannot give your manager read access to yours. **Workaround:** send the exported report and screenshots of Overview. Scheduled email digests are also **Not available yet**.

**If something does not work:** see [Troubleshooting](18-troubleshooting.md).

## Use case 9: Onboarding a second tenant or collection

**Goal:** add another customer (tenant) or another Qdrant collection to what RAGGuard audits.

RAGGuard has no "add tenant" button. Tenants are discovered from your data: from the tenant part of the S3 key, from the manifest \`tenant_id\` column, and from the vector payload \`tenant_id\`.

**Steps for a second tenant**

1. Make sure the new customer's documents sit under their own first-level folder (for example \`globex/...\`) so the default **Key pattern** (\`^(?P<tenant_id>[^/]+)/(?P<document_id>.+)$\`) sees them. If your bucket has no tenant folders, every document belongs to the **Default tenant** (\`default\` unless you changed it).
2. Make your pipeline write the same \`tenant_id\` in the manifest rows and in the vector payloads.
3. Check **Settings**, **Policy**, **Required payload fields**. If it is empty, RAGGuard requires \`tenant_id\` in every vector payload as soon as there is more than one tenant. Vectors without it raise **Metadata mismatch**. That is intended: with several tenants an untagged vector is a leak risk.
4. Run a full audit.
5. Check that the tenant appears: on **Overview**, **Tenant health**; on **Isolation**, the **Tenants** table (which also shows whether the new tenant is kept apart from the others); on **Reconciliation**, the **Tenant** filter and **Scoped audit** (the dialog lists each tenant with its document count).
6. From now on you can audit one tenant at a time with **Scoped audit** (with **Probe retrieval for the worst findings** on or off), which is faster than a full audit and leaves other tenants untouched.

**Steps for a second collection**

1. Open **Data sources**, click **Edit** on the Qdrant card.
2. In **Collections**, list the names separated by commas (for example \`kb_main,kb_new\`). Empty means every collection.
3. Click **Test connection**. The result shows one **Collection NAME** line and one **Payload of NAME** line per collection (for up to the first five). Fix anything red, then **Save**.
4. Run a full audit. A document is expected in at least one of the listed collections, and findings name the collection.

**If the second tenant belongs to another team:** a workspace is private to one account, and there are no shared workspaces (**Team** is **Not available yet**). Another team's systems need their own account and workspace.

**How to read the result:** per-tenant scores let you compare customers. A tenant with a low score, or many **Pending** documents, usually means its pipeline was only just switched on.

**If something does not work:** see "Zero issues when you expect some" and "Too many issues" in [Troubleshooting](18-troubleshooting.md).

## Use case 10: Reducing re-embedding cost

**Goal:** fix what is broken without re-embedding the whole corpus.

**Steps**

1. Open **Integrity issues**, **Repair plans**. The **Recommended work** card already shows the smallest safe set of repairs for your open issues: **Documents to reprocess**, **Chunks to regenerate**, **Estimated tokens**, **Estimated cost**, **Savings vs full reindex** (shown when it can be computed) and **Vectors to remove**. The small text below states the assumptions, such as the tokens per chunk and the price.
2. Make the estimate match reality: on **Settings**, **Policy** set **Embedding price (USD per 1M tokens)** and **Tokens per chunk (for estimates)**, then **Save**. They are used only for estimates.
3. Narrow the work. Use **Minimum severity** (for example **High and above**) to leave out minor issues, and watch the figures change.
4. Narrow it further. In the **Issues** tab, tick only the rows you want and click **Create repair plan**. Issues you have **Ignored** are left out.
5. Create the plan and compare. The plan's **Summary** repeats the figures. To compare with the alternative, run **Impact analysis** with **Pipeline change** and look at "Full reindex: ..." under **Estimated cost**.

**Why a plan can be cheaper than a full reindex**

| Issue | The smallest action | What it costs in embedding |
|---|---|---|
| Missing chunks (**Partial index**) | **Re-embed missing chunks**, only the missing ones | A few chunks |
| Wrong metadata (**Metadata mismatch**) | **Fix metadata**, no re-embedding | Nothing |
| Duplicates, superseded vectors, orphans, tenant mismatch | **Remove old vectors**, no re-embedding | Nothing |
| Missing, stale, drifted or empty embeddings | **Full reindex** of that document only | The chunks of that document |

A document with several issues gets the smallest set of actions. A full reindex already rewrites chunks and the manifest, so a document that gets **Full reindex** does not also get **Fix metadata**.

**How to read the result:** **Savings vs full reindex** compares your plan with re-embedding every document. For example, a plan for 3 documents out of 1,000 costs a small fraction of a full re-embed. The chunk counts come from the manifest's expected chunk counts and fall back to roughly 4 bytes of source per token when the manifest has none, so an unmapped \`expected_chunk_count\` makes the estimate rougher.

**If something does not work:** see [Troubleshooting](18-troubleshooting.md).

## Related chapters

- [End-to-end journey](15-end-to-end-journey.md)
- [Integrity issues](07-integrity-issues.md), [Repair plans](08-repair-plans.md) and [Impact analysis](09-impact-analysis.md)
- [Isolation](20-isolation.md)
- [Documents](10-documents.md) and [Audit history](11-audit-history.md)
- [Integrations](12-integrations.md), [Alerts](13-alerts.md) and [Settings](14-settings.md)
- [Reference: every value](17-reference.md) and [Troubleshooting](18-troubleshooting.md)
`;export{e as default};
