# Troubleshooting

This chapter is organised by what you see. Find the symptom, read the cause, apply the fix. The messages are quoted exactly as RAGGuard shows them, so you can search this page for the text on your screen. If nothing matches, go to the last section, which tells you what to collect for a bug report.

Most problems fall into three groups: a connection does not work (sections on connection tests and data source cards), the numbers are not what you expect (zero issues, too many issues, documents shown wrongly), or a repair does not progress. New words are explained in [Concepts you need](02-concepts.md), and every status and message value is listed in [Reference: every value](17-reference.md).

**On this page**

- [Sign-up and sign-in problems](#sign-up-and-sign-in-problems)
- ["Run audit" is disabled](#run-audit-is-disabled)
- ["Connect your data sources first"](#connect-your-data-sources-first)
- [Connection test messages](#connection-test-messages)
- [A data source card says Error or Status unavailable](#a-data-source-card-says-error-or-status-unavailable)
- [An audit stays running or fails](#an-audit-stays-running-or-fails)
- [Everything looks missing, or an audit warns about document IDs](#everything-looks-missing-or-an-audit-warns-about-document-ids)
- [Zero issues when you expect some](#zero-issues-when-you-expect-some)
- [Too many issues](#too-many-issues)
- [Documents shown as Failed, Missing or orphaned unexpectedly](#documents-shown-as-failed-missing-or-orphaned-unexpectedly)
- [Numbers differ between pages](#numbers-differ-between-pages)
- [Repair problems](#repair-problems)
- [API key problems](#api-key-problems)
- [Alerts not arriving](#alerts-not-arriving)
- [The page is not updating](#the-page-is-not-updating)
- [Browser tips](#browser-tips)
- [How to collect information for a bug report](#how-to-collect-information-for-a-bug-report)
- [Related chapters](#related-chapters)

## Sign-up and sign-in problems

| What you see | Cause | Fix |
|---|---|---|
| "Enter a valid email address." | The email is not in the form name@domain.tld | Correct the email |
| "Enter your password." | The password box is empty | Type it |
| "Use at least 10 characters." (sign-up form) or "Password must be at least 10 characters." | Passwords need 10 to 128 characters | Choose a longer one |
| "Password must be at most 128 characters." | The password is longer than 128 characters | Shorten it |
| "That password is too easy to guess." | It is on a short list of very common passwords, or it uses fewer than 4 different characters | Choose a less guessable one |
| "Password must not contain your email name." | The part of your email before the `@` (when it is 4 or more characters) appears in the password | Remove it from the password |
| "An account with that email already exists." | You (or someone) signed up with this email before | Use the **Sign in** tab instead |
| "Invalid email or password." | Wrong email or password. The message is the same whether or not the email exists. | Retype carefully. There is no password reset in this version (see below). |
| "Too many sign-in attempts. Wait a few minutes and try again." | More than 8 attempts for one account, or 30 from one network, in 15 minutes | Stop trying and wait. Repeated attempts only extend the wait. |
| "Too many sign-ups from your network. Try again later." | More than 5 sign-ups from one network in an hour | Wait, or ask someone on a different network |
| "New sign-ups are closed on this server." (or "Registration is closed on this server.") | The operator closed sign-up | Ask the operator for an account. Existing users can still sign in, and only the **Sign in** tab is shown. |
| "Cross-site request blocked." | A request that changes data arrived with your session cookie but without a matching origin | Use the app from the same address you signed in on, and see [Browser tips](#browser-tips) |
| The screen "This server isn't fully set up yet" with a list | The operator has not finished the server set-up. The list says what is missing, for example that the secret key or the database is not configured, or that the database schema is out of date. | Tell the operator. Click **Check again** after they fix it. |
| You were signed out | Your session ended (it lasts 7 days and is renewed as you use the app), you signed out, or you changed your password on another device, which ends the other sessions | Sign in again. You land on the page you were trying to open. |

**I forgot my password.** There is no password reset and no email verification in this version. Your operator can remove your account so you can sign up again, but removing an account deletes everything in its workspace (connections, issues, history and plans).

**Changing your password.** **Settings**, **General**, **Change password**. You need your current password, the new one (10 to 128 characters) and a confirmation. Other signed-in sessions are signed out. The messages are "Enter your current password.", "Use at least 10 characters.", "Choose a password that is different from the current one.", "The two passwords do not match." and "Your current password is incorrect."

## "Run audit" is disabled

Hover over the dimmed button (or focus it with the keyboard). The tooltip gives the reason.

| Tooltip or label | Cause | Fix |
|---|---|---|
| "Connect your data sources first" | Not all three systems are configured. A system counts as configured when its required fields are saved: the S3 Bucket, Access key ID and Secret access key; the manifest Connection string; the Qdrant URL. | Open **Data sources** and finish the cards marked **Not connected** (see [Connect your data sources](04-data-sources.md)). A saved connection counts even if you have not tested it. If you saved all three and the button is still dimmed, reload the page. |
| "An audit is already running" | Another audit is in progress. It may have been started by another browser tab, by a script, or by a repair plan's **Verify now**. | Wait. **Overview** and the run page refresh every 3 seconds while an audit runs. Check **Audit history** for a run with the status **Running**. |
| The button shows "Audit running" with a spinner | An audit that you started is in progress | Wait for the toast "Audit complete" or "Audit failed" |
| "Audit running" never goes away | The run was cut off before it could save a result, for example because the hosting function was stopped | RAGGuard marks a run that has been "running" too long as Failed, with "abandoned: the process running it stopped" and the last step it reached. On a hosted server this happens about 360 seconds after the start (the 270-second time budget plus 90 seconds). Reload the page; the button is enabled again. See [An audit stays running or fails](#an-audit-stays-running-or-fails). |

## "Connect your data sources first"

You see this text in several places: the title of an empty state on **Integrity issues** and **Documents**, an error card ("Connect your data sources first, RAGGuard needs your S3 source, manifest database and Qdrant index before it can compare them"), and the button tooltip. On **Reconciliation** the title reads "Connect your data first". It means your workspace is not ready, or a request was refused with the message "Finish setup first: connect S3 source documents, the processing manifest, the Qdrant index in Settings." (the list names only what is missing).

**Fix:** open **Data sources** (the button **Go to Data Sources** takes you there) and connect whatever is missing. On **Overview** the card "Connect your data" shows which of the three steps are **Done** and which are **To do**.

## Connection test messages

**Test connection** in a data source dialog checks what you typed without saving it. **Test** on a card checks what is saved and remembers the result. Each check line is green (ok), amber (warning) or red (failed). A message that begins with the name of a field and a colon (for example "URL: ...") is a problem with that field's value, shown in a red box above the buttons.

### Amazon S3

| Message | What it means | What to change |
|---|---|---|
| Configuration: "Fill in the required fields first: Bucket, ..." | A required field is empty | Fill in the fields listed |
| Bucket reachable: "The bucket does not exist (check the name and region/endpoint)." | No bucket with that name was found | Check the **Bucket** spelling, **Region** and **Custom endpoint** |
| Bucket reachable: "Access denied: the key needs s3:ListBucket on the bucket and s3:GetObject on its objects (AWS requires GetObject for the HEAD requests that read content hashes). Both are read-only." | The access key is valid but its permissions are too small | Give its user `s3:ListBucket` on the bucket and `s3:GetObject` on `bucket/*` |
| "The access key ID is not recognised by this endpoint." | The key id is wrong, deleted, or belongs to another provider or endpoint | Re-enter the **Access key ID**; for an S3-compatible store set its **Custom endpoint** |
| "The secret access key is wrong, or the region does not match the bucket." | The signature failed | Re-enter the **Secret access key**, and set **Region** to the bucket's own region |
| "No usable credentials: fill in both the access key ID and the secret access key." | One of the two keys is missing | Fill in both |
| "Could not connect to the S3 endpoint. Check the endpoint URL (leave it empty for AWS S3) and that it is reachable from the internet." | The address did not answer in time | Leave **Custom endpoint** empty for AWS. For another provider, check the address and that it is public. |
| "Not found: check the bucket name." or "Access denied: check the access key permissions." | The store answered with a bare 404 or 403 | Same as above |
| A message that starts with an error name such as "ClientError: ..." followed by the store's text | An error RAGGuard has no plain-language text for. A text about a region or a redirect means **Region** does not match the bucket's region. | Fix the field the text points to |
| Documents found (amber): "No objects under this bucket/prefix yet. The audit will report an empty source." | The bucket or the **Key prefix** holds no files | Check **Key prefix**; add documents |
| Key pattern (red): "None of the sampled keys (e.g. ...) match the key pattern. Adjust 'Key pattern' so it captures document_id (and optionally tenant_id)." | Your keys do not fit the pattern, so every document would be ignored | Change **Key pattern**. The default expects `tenant/path/to/document.pdf`. For a flat bucket use `^(?P<document_id>.+)$`. |
| Key pattern (amber): "N of M sampled keys match; e.g. ..." | Some keys do not fit and will be ignored | Fine if intended (for example other folders). Otherwise adjust the pattern or **Key prefix**. |
| Content hashes (amber): "N of 5 sampled objects carry a SHA-256 ...; the others fall back to the ETag, which is flagged unreliable for multipart uploads" | Some objects have no SHA-256 in user metadata (or as an S3 checksum) | Store the SHA-256 when you upload, or use **Content hash** `compute` (downloads each object; costs time and transfer) |
| Content hashes (amber): "hash mode 'etag': ETags are not content hashes for multipart uploads" | You chose `etag` | Acceptable for a quick start. Stale-document findings become medium for multipart objects. |
| Object metadata (red) with an access message | Reading the details of an object failed, usually because `s3:GetObject` is missing | Add `s3:GetObject` |
| Field message: "Key pattern (regex): must contain a `(?P<document_id>...)` group" or "is not a valid regular expression" | The pattern is wrong | Add the `document_id` group, or fix the expression |

### PostgreSQL manifest

| Message | What it means | What to change |
|---|---|---|
| Database reachable: "Authentication failed: check the user name and password in the connection string." | Wrong user or password | Fix the **Connection string** |
| "Connection timed out: the host is unreachable from the internet or a firewall blocks this server." | The database did not answer | Check the host and port, and allow this server through your firewall |
| "The host name could not be resolved." | The host name in the string does not exist | Fix the host |
| "SSL negotiation failed: try adding ?sslmode=require to the connection string." | The server needs (or refuses) SSL | Add `?sslmode=require` |
| "Permission denied: the role cannot read this table." | The database user cannot `SELECT` the table | Grant `SELECT` on the table to the role |
| Manifest table: "table public.rag_document_manifest was not found or has no mapped columns." (the schema and table shown are yours) | **Schema** or **Document table** is wrong, or none of the table's columns match RAGGuard's names | Fix the names, or map your columns with **Column map (JSON)** |
| Manifest table: "no column for document_id (looked for 'document_id'). Map it with the column map." | The table has no `document_id` column | Map it, for example `{"document_id": "doc_ref"}` |
| Manifest table: "could not inspect ...: ... Check schema/table names and that the role can read them." | The table could not be examined | Check names and permission |
| Columns used for checks (amber): "missing source_hash, ...: the related checks (stale / partial / false-success detection) are reduced." Also shown as "Unmapped columns" on the card | The table lacks, or you have not mapped, columns RAGGuard uses for its best checks | Map them with **Column map (JSON)** (RAGGuard's name on the left, yours on the right). Not fatal, but those checks get weaker. |
| Rows (amber): "the manifest table is empty" | The table has no rows | Check you pointed at the right table |
| Role is read-only (amber): "this database role CAN write to the manifest table. RAG Integrity only reads (every query is READ ONLY), but a SELECT-only role is safer." | Your role has write rights | Optional: create a `SELECT`-only role. The test still passes. |
| Chunk manifest (red): "... needs document_id and chunk_id columns" | The **Chunk table** lacks required columns | Map them with **Chunk column map (JSON)**, or clear the field |
| Chunk manifest (amber): "not configured: partial indexes are detected from chunk counts and index gaps instead of exact chunk ids." | You gave no **Chunk table** | Fine. A chunk table lets RAGGuard name exactly which chunks are missing. |
| Configuration (red): "Unknown manifest column 'x'; valid: ..." | A key in the column map is not a RAGGuard column name | The left side of each map entry must be one of the listed names |
| Field message under **Connection string**: "That is not a valid database URL.", "Only postgresql:// connection strings are supported.", "The database URL needs a network host (unix sockets are not allowed).", "Unsupported connection option(s): x. Allowed: application_name, connect_timeout, sslmode.", "Invalid database port." | The string breaks a rule that keeps the connection safe | Use `postgresql://user:password@host:5432/dbname?sslmode=require` with only the allowed options |
| Field message: "Schema: Invalid Schema '...': only letters, digits and underscores are allowed" (same for **Document table** and **Chunk table (optional)**) | The name has a character that is not allowed | Use letters, digits and underscores only |

### Qdrant

| Message | What it means | What to change |
|---|---|---|
| Qdrant reachable: "Qdrant rejected the API key (a read-capable key is required)." | A 401 or 403 from Qdrant | Enter a valid read-capable **API key** |
| "Connection refused: check the URL and port." | Nothing is listening there | Fix the **URL** and port. A URL without a port uses 6333. If Qdrant is behind a TLS proxy, add `:443`. |
| "The host name could not be resolved." | The host name is wrong | Fix the **URL** |
| "Qdrant timed out. Check the URL and port (Qdrant Cloud uses `https://CLUSTER:6333`). On a very large collection, filtering by a field that has no payload index is slow: ask the cluster owner to create a keyword index on the document id field (for example source_id)." | No answer in time | Check the address. For large collections create a payload index on the document id field. |
| Collections (red): "not found: x. Existing: a, b." | A name in **Collections** does not exist | Correct the name, or empty the field to audit every collection |
| Collections (amber): "this Qdrant has no collections yet." | An empty cluster | Check you are on the right cluster |
| Collection `name` (amber): "the collection is empty" | The collection holds no points | Check the name |
| Payload of `name` (red): "sampled points carry no document_id. Map the payload field names with the payload map." | RAGGuard cannot tell which document a vector belongs to | Map the field with **Payload field map (JSON)**, for example `{"document_id": "doc_id"}` |
| Payload of `name` (amber): "sampled points lack source_hash: freshness checks will be limited." | Vectors carry no content hash | Make your pipeline write `source_hash` into every payload |
| "Qdrant needs a payload index on the field used to filter by document (strict mode). Ask the cluster owner to create a keyword index on it, or turn off 'Only audit documents found in the source (S3)'." | Qdrant's strict mode refuses to filter on a field without an index | Create a keyword index on the document id field, or turn that switch off |
| "Not found: check the collection name." | A collection could not be found | Check **Collections** |
| Connection (red): "ValueError: Unknown payload field 'x'; valid fields: ..." | A key in the payload map is not a RAGGuard field name | The left side of each entry must be one of the listed names |

### Addresses that are refused (all systems)

In hosted mode every address you enter must be public. The refusal appears as a red message that starts with the field's label (for example "URL: localhost is not a public host name."), or as a **Configuration** check.

| Message | Cause | Fix |
|---|---|---|
| "HOST is a private or reserved address; only public hosts are allowed." | An IP address on a private network, loopback, link-local, or another reserved range | Use a public address |
| "HOST is not a public host name." | `localhost`, or a name ending in `.local`, `.internal`, `.lan`, `.home.arpa` | Use a public name |
| "Could not resolve HOST." | The name does not resolve in DNS | Fix the name |
| "HOST resolves to a private or reserved address; only public hosts are allowed." | A public-looking name that points to a private address | Point it at a public address |
| "A host name is required." | The address has no host | Complete it |
| "URL must start with https:// or http://." | Wrong scheme | Add `https://` |
| "Do not put credentials inside the URL." | A user name or password is in an address | Remove them. For Qdrant use the **API key** field. |
| "Invalid port in URL." | The port is not a valid number | Fix it |

If your systems are on a private network, expose a public endpoint to them (for example through a tunnel or a proxy), or ask your operator whether the server was set up to allow private addresses. A user cannot change this setting.

### Other messages while connecting

| Message | Meaning |
|---|---|
| "Too many connection tests. Try again in a few minutes." | The limit is 30 tests per workspace in 10 minutes. This stops the server being used to scan networks. |
| "Nothing to check yet. Fill in a field first." | You pressed **Test connection** on an empty form |
| **Save** is dimmed | Nothing has changed since the last save |
| Inline under a field: "X is required.", "The address must start with https:// or http://.", "The connection string must start with postgresql://.", "The pattern must contain a `(?P<document_id>...)` group.", "Use letters, digits, _, - and . only, separated by commas.", "Enter a JSON object with text values, for example {"document_id": "doc_ref"}.", "Not valid JSON (...).", "Enter a whole number.", "Enter a number.", "Choose one of: ..." | The value breaks the field's format. The server may add a range message such as "Chunk size: must be between 1 and 1000000". |

## A data source card says Error or Status unavailable

**Error (red).** The card is configured, but the live check failed. The line under the title is the error. On a card that line can be the raw error text, for example one that starts with "ClientError:", because the card shows the technical message. Click **Test** on the card for the plain-language explanation. Usual causes: a key was rotated or deleted, the bucket was renamed, a database password changed, a host moved, a firewall changed, or the Qdrant key changed.

| Card line | Meaning |
|---|---|
| "table X not found or has no mapped columns" | The manifest table name is wrong, or none of its columns match |
| "X has no document_id column" | The manifest table has no `document_id` (or a mapped equivalent) |
| "collection(s) not found: x" | A name in **Collections** does not exist in Qdrant |
| "bucket 'x' reachable, hash mode 'metadata'; N sample key(s) don't match RAGI_S3_KEY_PATTERN" | Works, but some sampled keys do not fit your **Key pattern** |

**Status unavailable (amber).** "Live status is unavailable right now" means the server could not run the check (it may have been briefly unreachable). Click **Refresh status** at the top of the page.

**Checking (blue)** is shown while the live check runs and should pass within seconds.

After you save a new configuration, an earlier test result on the card is cleared, because it no longer applies.

## An audit stays running or fails

Where to read the reason: the red message on **Overview** under **Last audit**, the "This audit failed" panel on the run's page in **Audit history**, the toast "Couldn't start the audit" or "Audit failed", and the **Error** shown in the Activity log.

| What you see | Cause | Fix |
|---|---|---|
| "The audit ran out of time while reading the source bucket (listed N objects so far). This corpus is too large to audit in one go here: audit one tenant at a time, narrow the source (for example the S3 key prefix), or run `ragi audit` on a machine without a request time limit." The thing being read can also be "the processing manifest", "the chunk manifest" or "the vector index". In Audit history the message starts with "AuditTimeout:". | On a hosted server an audit has 270 seconds (the hosting function stops at 300). Your corpus is too big to finish within that. | Audit one tenant at a time with **Scoped audit**. Set a **Key prefix**. For a very large bucket switch on **Look up files from the manifest (skip listing the bucket)**, which needs one request per listed file instead of listing everything and requires the manifest's `source_uri` to be mapped. Use **Content hash** `metadata` rather than `compute`. For a collection shared with other products switch on **Only audit documents found in the source (S3)**. Or ask your operator to run `ragi audit` on a machine without a time limit. |
| "Qdrant timed out. ..." | One Qdrant request took more than about 60 seconds, usually a filter on a field without an index | Ask the cluster owner to create a keyword index on the document id field |
| "abandoned: the process running it stopped (last step: reading the vector index (Qdrant), N s in)" | The process that was running the audit stopped before it could record a result, for example because the host stopped it | The text after "last step" says where it got to; apply the matching fix from the first row. Start the audit again. |
| "An audit is already running." / "An audit is already running for this workspace." | Only one audit can run at a time per workspace | Wait for the other one |
| "Finish setup first: connect ..." | A required connection is missing | See [Connect your data sources first](#connect-your-data-sources-first) |
| The message names one of your systems, for example an access denied text, "Qdrant rejected the API key ..." or "Authentication failed ..." | A connection stopped working since you last tested it | See [Connection test messages](#connection-test-messages) |

## Everything looks missing, or an audit warns about document IDs

An audit can only match documents whose ID is the same in S3, the manifest and Qdrant. When the IDs differ, most documents look missing or orphaned and the numbers are noise. Start with the **Setup check** on **Data sources**: it compares the IDs in plain words ([The Setup check](04-data-sources.md#the-setup-check)).

| What you see | Likely cause | Fix |
|---|---|---|
| **Files in S3** needs fixing: none of the file names match the key pattern | The **Key pattern** does not fit your file names (for example it expects `.pdf` and the bucket holds `.md`) | Change the **Key pattern** in the S3 dialog so it captures the document ID from the real file names the check shows, save, and check again |
| **S3 against the manifest** is red or amber, and the IDs at a glance look alike but are not the same (`2329961` and `bill-2329961`) | S3 and the manifest write the ID differently | Make both sides write the ID the same way, or change the key pattern. RAGGuard compares IDs exactly: an ID clean-up rule is not available yet |
| **Tenant names agree** needs fixing | The systems use different tenant names, or one side has none | Make the tenant names match, or set the **Default tenant** for data without tenants |
| **S3 against Qdrant** is low | The IDs in the Qdrant payload differ from the file IDs, or those documents are not indexed yet | Compare the IDs at a glance; map the Qdrant payload field that holds the document ID |
| **Qdrant against S3** says most of the index belongs to other documents | The collection is shared with other sources | Turn on **Only audit documents found in the source (S3)** under **Settings**, **Policy**. The row then passes: it was information, not a problem |
| An amber notice on **Overview** and a warning on the audit's page: more than one file in S3 shares an ID | A key pattern that captures only the file name, while the same name exists in two folders | Change the key pattern so every file gets its own ID (for example include the folder), or remove the extra copies |
| The warning says more than one manifest row shares an ID | Old rows were left behind when a document was processed again, or the mapped ID column is not unique | Remove the old rows, or map a column that is unique per document as the document ID |
| The warning says some manifest rows have no document ID | The column map points at the wrong column | Check the column map for the manifest on **Data sources** |

These warnings do not make an audit's findings wrong: the audit followed one item per ID, and the warning tells you what it could not see. Fix the cause, run a full audit, and the warning goes away.

## Zero issues when you expect some

Work through these in order. Each is a way the audit can legitimately see less than you expect.

| Check | How to tell | Fix |
|---|---|---|
| You are looking at a filter | The **Issues** tab shows **Open** issues only by default. Ignored and resolved issues are hidden. A severity chip or other filter may be on. | Click **Clear filters**, or set **Status** to **All statuses** |
| No audit has run, or the last one failed | **Overview** says "No audit has run yet", or **Last audit** is red | Run an audit and read any error |
| You only ran a scoped audit | The run's **Scope** is a tenant or "N documents" | Run a full audit. The results on **Reconciliation** come from the latest full audit. |
| Your documents are not being found | **Source documents** on **Reconciliation** is 0 or too low | Run the **Setup check** on **Data sources**: it shows real file names next to your pattern. Check **Key prefix** and **Key pattern**. Keys that do not match the pattern are ignored (the Setup check counts them), and so are keys that end in `/`. |
| Documents are still inside the grace period | They are listed as **Pending** under **Document status** | Wait, or reduce **Grace period (minutes)** on **Settings**, **Policy** |
| **Only audit documents found in the source (S3)** is on | The switch on the **Policy** tab | With it on, orphan vectors, orphan manifest rows and tenant mismatches are not reported, by design |
| **Look up files from the manifest (skip listing the bucket)** is on | The switch in the S3 dialog | A file that is in S3 but not in the manifest is not discovered, so "never ingested" documents are not reported |
| Wrong or narrow **Collections** | Only the collections listed are audited | Correct the names, or empty the field for every collection |
| Vectors have no document id | One issue "Vectors without a document id" instead of document issues | Map the field with **Payload field map (JSON)** |
| Vectors carry no hash or version | In a document's **Chunks** tab (**Inspect live**) the class is `unknown` | Make your pipeline write `source_hash` (and ideally a version) into every payload. Without it RAGGuard cannot tell whether a vector is current. |
| Manifest columns are not mapped | The manifest card shows "Unmapped columns" | Map `source_hash`, `processing_status`, `expected_chunk_count` and `indexed_chunk_count` so the stale, partial and false-success checks are complete |
| No target pipeline set | **Settings**, **Pipeline** is empty | Drift is only reported for vectors of one document that disagree with each other. Set the target to detect drift against it. |
| **Detect empty embeddings** is off | The switch on the Qdrant card | Empty or all-zero vectors are only checked when it is on |
| Every issue was ignored | **Status** set to **Ignored** shows them | Reopen what no longer applies |
| The index really is healthy | A green **Health score** with no open issues | To be sure, pick a document you know is wrong, open it on **Documents** and click **Inspect live**. If live shows a problem the audit does not, use the rows above. |

## Too many issues

| What you see | Cause | Fix |
|---|---|---|
| Almost every document has **Stale document version** | The hash RAGGuard reads from S3 is not the value your pipeline stored as `source_hash`. Common reasons: the pipeline hashes something else, the objects carry no SHA-256 so RAGGuard fell back to the ETag, the **SHA-256 metadata key** name differs, or the uploads were multipart. | Open one document, **Chunks** tab, **Inspect live**. Compare the source hash, the manifest's source hash and the vector classes. Make them the same value, or use **Content hash** `compute` as a reference. Then audit again. |
| Almost every document has **Pipeline drift** | The target pipeline on **Settings**, **Pipeline** does not match what your pipeline records. Values are compared as text, so `recursive-v2` and `recursive_v2` differ. An empty target does not cause this; a wrong one does. | Correct the target, or clear the fields you are unsure of |
| A **Critical** "Collection vector size does not match the target embedding model" | **Embedding dimensions** differs from a collection's vector size | Fix the number, or point the audit at the collection built with the new model |
| Many **Missing embeddings** and many **Orphan vectors** with similar names | The same document is named differently in different systems | See [Documents shown as Failed, Missing or orphaned unexpectedly](#documents-shown-as-failed-missing-or-orphaned-unexpectedly) |
| Many **Metadata mismatch** that mention missing payload fields | The vectors lack a field you require. With more than one tenant, `tenant_id` is required by default. | Make the pipeline write the field, or set **Required payload fields** to what your vectors really carry |
| Many **Metadata mismatch**: "Manifest says N chunks indexed, the index holds M." | The manifest's `indexed_chunk_count` is counted differently from the chunks in the index, or is out of date | Check how the pipeline fills that column, or map the right column |
| **Superseded vectors active** after a re-index | Old and new vectors of a document exist together until cleanup | Normal. Approve the cleanup of the repair plan. |
| Orphan vectors for documents you never had | The index or manifest is shared with other products | Switch on **Only audit documents found in the source (S3)**, set a **Key prefix**, or limit **Collections** |
| Many **Pending** documents | Ingestion is running right now, or the grace period is short | Wait, or raise **Grace period (minutes)** |
| The first audit of an old system looks bad | It reflects real history | Triage by severity (critical first), ignore what you accept with a reason, and repair the rest in plans |

## Documents shown as Failed, Missing or orphaned unexpectedly

**What "Failed" means.** On **Documents** the **Embedding status** "Failed" does not mean a job failed. It is the label for a document whose audit status is **Broken** or **Orphaned** (and that has no missing or stale issue). Open the document to see why.

**The id must be the same in all three systems.** RAGGuard matches a document across S3, the manifest and Qdrant by its **tenant** and its **document id**.

- In S3 the id comes from the key. The **Key prefix** is removed first, then the **Key pattern** is applied. With the default pattern, `acme/policies/leave.pdf` is tenant `acme` and document `policies/leave.pdf`.
- In the manifest it is the `tenant_id` and `document_id` columns.
- In Qdrant it is the `tenant_id` and `document_id` payload fields.

If one system writes `leave.pdf` where another writes `policies/leave.pdf`, RAGGuard sees two different documents: one that exists in S3 with no vectors (**Missing embeddings**), and one that has vectors but no source (**Orphan vectors**). On **Documents**, search for part of the name and look for the pair.

| Symptom | Cause | Fix |
|---|---|---|
| Documents with a red cross in **Source** but a tick in **Index** | The source key is not what the vectors say, or the file really was deleted | Compare the ids shown. Fix the **Key prefix**, **Key pattern**, **Payload field map (JSON)** or **Column map (JSON)**, or fix the pipeline's ids |
| Documents with a tick in **Source** and a red cross in **Index** and **Manifest** | The pipeline never processed them, or wrote them under a different id | Same as above, then repair |
| Everything is under one tenant, or tenants look wrong | The key pattern has no `tenant_id` group, so every document gets the **Default tenant**, while the manifest or vectors name real tenants | Add a tenant group to **Key pattern**, or write the tenant consistently |
| Documents are missing from the source side | The **Key prefix** is too narrow, or the keys do not fit the pattern | Test the S3 card and read **Key pattern** |
| A document shows as **Processing** for a long time | It was changed, or its manifest status is in flight, within the grace period | Wait. A document stuck in flight for longer than the grace period is reported with the time it has been stuck. |
| "Document not found" when opening a document | RAGGuard has no record of it in this workspace | Run an audit; check the key pattern |

## Numbers differ between pages

| You notice | Reason |
|---|---|
| The **Health score** on Overview differs from the score of the last audit | Overview shows the score of all documents as of now. A scoped or verification audit refreshes only its documents, so it can move the score; a run's own score covers only its scope. |
| **Health over time** has fewer points than there are audits | It draws one point per completed **full** audit, and needs two to draw a line |
| The health score did not change after you ignored issues | Ignoring changes the issue list, not how documents are judged |
| **Open issues** is lower than **Findings** in the last audit | Findings counts what that audit found. Open issues counts issues that are open now, which excludes Ignored ones. |
| **Resolved** is 0 on a full audit that followed a verification | The verification audit already resolved the issues in the plan's documents |
| **Unchanged** and **Escalated** overlap | An issue whose severity went up is counted under both |
| The runs table shows "Api" as the trigger for runs you started in the browser | The web interface uses the same API as scripts. Both show **Api**. |
| The exported report omits healthy documents | It lists only documents with open issues. The API's `include_healthy=true` adds the rest. |

## Repair problems

### The webhook

| Message or symptom | Cause | Fix |
|---|---|---|
| "No repair webhook configured. Set RAGI_REPAIR_WEBHOOK_URL (and RAGI_REPAIR_WEBHOOK_SECRET) to hand repairs to your ingestion worker, or export the plan from GET /api/repairs/{id}/payload." and the amber note "No repair webhook is set up yet, so triggering will fail." | No webhook address is saved. (The message names server settings; in the hosted app you set them on the **Integrations** card.) | **Integrations**, **Repair webhook**, **Configure**: set **Webhook URL** and **Signing secret**, **Check settings**, **Save**. Or use **View payload** to copy the request and give it to your worker by hand. |
| "RAGI_REPAIR_WEBHOOK_SECRET must be set before payloads are sent to a real webhook." | The **Signing secret** is empty. The card shows "A signing secret is required before anything is sent." | Open **Edit** and enter a **Signing secret** |
| "Repair webhook delivery failed: ..." followed by an error type and status, with your worker address replaced by `<webhook>` (for example `HTTPStatusError: Server error '500 Internal Server Error' for url '<webhook>'`) | Your worker did not accept the request: it was unreachable or too slow (RAGGuard waits 30 seconds, once), or it answered with an error status such as 401 (invalid signature), 404 (wrong path) or 500 | The plan stays **Draft**. Fix the worker (check its log, that it verifies with the same secret over the raw body, and that its clock is within 5 minutes of the real time), then click **Trigger repair** again |
| "HOST is not a public host name." when saving the webhook | The worker address must be public in hosted mode | Use a public address |
| "Plan is 'triggered'; only draft, partial or failed plans can be (re)triggered." | The plan was already sent | Wait for your worker, then **Verify now** |

### Verification

| Message or symptom | Cause | Fix |
|---|---|---|
| "Trigger the plan before verifying it." | A Draft plan cannot be verified | **Trigger repair** first |
| The plan stays **Triggered** | Your worker has not finished, or it does not call back | Click **Verify now** when it has finished. A callback must be signed with the same secret, or RAGGuard answers "Invalid callback signature." |
| Documents are **Not fixed yet** with "Still found: ..." | The new data in your index does not match the source. Verification re-audits the real index, and does not trust the worker. | See the table below, then **Send repair again** (only failed documents are sent) and **Verify now** |

What "Still found" tells you:

| Still found | What to check in your worker |
|---|---|
| missing embedding, partial index | It did not write all chunks, wrote to a different collection, or used a different document id or tenant than the source |
| stale embedding | It did not re-read the latest source, or wrote an old `source_hash`. It must store the source's hash in every payload and in the manifest. |
| metadata inconsistent, pipeline drift | It did not update the manifest (`source_hash`, `indexed_chunk_count`, `indexed_version`, pipeline fields), or it used a model or chunking that is not your target pipeline |
| superseded, duplicate, orphan or tenant mismatch (the "Old vectors removed" check) | Expected until cleanup; this is not a failure of the first four checks |

### Cleanup not offered

**Approve cleanup** appears only when the plan is **Cleanup pending**.

| Symptom | Cause | Fix |
|---|---|---|
| No **Approve cleanup** button | The plan is not **Cleanup pending**. Removal comes only after documents are verified. | Trigger, wait, **Verify now**. Documents that failed verification keep their old vectors, and removal covers only verified documents. |
| "Cleanup can only be approved once replacements are verified (plan is 'draft')." | Same | Same |
| "Nothing is eligible for cleanup yet: documents must first pass verification." | No document is in **Replacements verified** or **Waiting for cleanup** | Fix the failing documents first |
| "No superseded vectors found any more - run verify again." | Nothing is left to remove (someone already removed them) | **Verify now**, and then **Run full audit** |
| A **Draft** plan whose documents are all "Remove old vectors", and **Trigger repair** answers "This plan has nothing to reprocess (cleanup only). Use approve-cleanup." | A known limit in this version. **Trigger repair** sends only documents that need re-processing, and **Approve cleanup** is offered only after a trigger and a verify, so a plan made only of removal work (orphan, duplicate, superseded or tenant-mismatch vectors) cannot progress. | Remove the vectors in your own tools (the evidence lists them; **Raw evidence (JSON)** has the point ids) and run another audit. Or create the plan with **Create plan from recommendations** when it also contains at least one document that needs re-processing; after **Verify now** the removal-only documents show **Waiting for cleanup** and are removed on **Approve cleanup**. |
| You chose **Automatic** under **Vector removal** | Removal is requested right after a successful verification, so you never see **Cleanup pending** | Expected. The plan goes to **Cleanup triggered**. |
| The confirmation says "Remove 0 old vectors?" although a cleanup will remove vectors | The number is the plan's estimate from when it was created. The exact list is read again from your index when you confirm. For documents that were stale when the plan was made, the old vectors only count as removable after the repair, so the plan's estimate can be 0. | Go ahead if the plan is right. The plan's **History** entry "Cleanup sent to your worker" shows the number actually sent. |
| After **Approve cleanup**, old vectors are still there | Your worker has not deleted them yet, or did not delete the exact point ids in the request | After it runs, click **Verify now**. If "Old vectors removed" still fails, the plan returns to **Cleanup pending** and you can approve again. |

### Plan creation

| Message or symptom | Cause | Fix |
|---|---|---|
| "No open document-level issues match that selection." | There is nothing to repair for that selection. Plans use open issues on specific documents only: Ignored and Resolved issues, and "Whole collection" issues, are not included. | Pick other issues, or lower **Minimum severity** |
| The **Create repair plan** button is dimmed with the tooltip "Only open issues on a specific document can be repaired" | Your selection holds only collection-wide or non-open issues | Select open document issues |
| "Nothing to repair" in **Recommended work** | No open document issue at or above the chosen **Minimum severity** | Choose a lower minimum |

## API key problems

| What you see | Cause | Fix |
|---|---|---|
| `401` with "Sign in required." | The key is missing, mistyped, revoked, or sent in the wrong form. In hosted mode a key that is not recognised looks the same as no sign-in. | Send `Authorization: Bearer ragi_...` (with the word `Bearer` and a space). Check there is no extra space or line break. If you lost the token, revoke the key and create a new one: the token cannot be shown again. |
| `401` with "Missing or invalid API key" | A single-user server protected by its shared key | Send it as `X-API-Key` or as a Bearer token |
| `403` with "This action needs a signed-in session, not an API key." | You called a session-only action: settings, connection tests, API keys, or changing a password | Do it in the browser |
| `403` with "Cross-site request blocked." | A browser cookie was sent with the request but no matching origin | Call the API with the key only, and no cookies |
| `409` with "An audit is already running." | Another audit is in progress | Try again later |
| `409` with "Finish setup first: connect ..." | A connection is missing | Finish **Data sources** |
| `422` | A required value is missing, or the body is not sent as JSON | Send `Content-Type: application/json` and a valid body |
| `429` | A rate limit was hit | Wait and retry less often |
| `502` | One of your systems refused or failed; the message says which | See [Connection test messages](#connection-test-messages) |
| `503` | "This deployment is not set up yet.", or a connection could not be built | Tell your operator, or check **Data sources** |
| `504` | The audit used up its time budget | See [An audit stays running or fails](#an-audit-stays-running-or-fails) |
| "You can have at most 20 API keys. Revoke one first." | The limit is 20 keys | Revoke one you no longer use |
| **Last used** says "Never" | The key has never been used successfully | Test it with `curl -H "Authorization: Bearer ..." https://your-address/api/overview` |

## Alerts not arriving

| Check | What to look at | Fix |
|---|---|---|
| Is a webhook saved? | The badge on the **Alert webhook** card says **Configured**. The address is never shown again after saving; the form says "A value is saved". | Save a **Webhook URL**. It must be a public address. |
| What did the last audits do? | **Recent deliveries**, with **Show** set to **Every audit**. Each row has an outcome and a reason. | See the next rows |
| "No alert webhook was configured." | No address saved | Save one |
| "No new issues at or above the minimum severity." | An alert is due only for issues that are **new**, **reopened** or **escalated**, and at or above **Minimum severity** (default `high`). An issue that stays open and unchanged never alerts again, so a steady state is silent. | Check the **Opened**, **Reopened** and **Escalated** counts of the run. If they are 0, nothing was due. Lower **Minimum severity** if you want more. |
| **Failed** with an error text such as `HTTPStatusError: Client error '404 Not Found' for url '<webhook>'` (the address is always replaced, so it is safe to copy) | The webhook did not accept the message. RAGGuard tries once and waits 10 seconds; it does not retry, and it does not resend later. | Fix the address (a Slack webhook that was deleted or regenerated is the usual cause). Missed alerts are not resent, so check **Integrity issues** for what you missed. |
| "Check settings" showed no message in Slack | **Check settings** only validates the values and sends nothing | To test the webhook itself, send a test message to it yourself, for example `curl -X POST -H "Content-Type: application/json" -d '{"text":"test"}' YOUR_WEBHOOK_URL` |
| The message went to the wrong channel | The webhook decides the channel | Create a webhook for the right channel |
| You wanted email, per-type rules, or a digest | **Not available yet** | Use the webhook (for example into a channel that forwards to email). The only filter is **Minimum severity**. |

## The page is not updating

| What you see | Reason | Fix |
|---|---|---|
| A list does not show the audit you started from a script or another tab | Lists load when you open a page and refresh after your own actions. Only **Overview** (and a run's page) refresh by themselves, every 3 seconds, while they know an audit is running. | Reload the page |
| **Data sources** shows an old status | The live status is checked when you open the page and kept for 30 seconds | Click **Refresh status** |
| A filter hides rows you expect | Filters and tabs are kept in the page address, so a shared or bookmarked link carries them | Click **Clear filters** |
| "Showing the first 500 of N. Narrow the filters." | The page loads at most 500 rows of a list | Narrow the filters |
| The new settings have no effect | Settings apply from the next audit onwards, not to earlier results | Run a new audit |
| The open-issue count in the left menu is old | It refreshes after audits and actions | Reload |
| After an update of the product the page looks odd | Your browser kept old files | Hard reload: **Ctrl+F5** (Windows, Linux) or **Cmd+Shift+R** (Mac) |

## Browser tips

- Use a current version of a mainstream browser, with JavaScript and cookies enabled. Signing in uses a cookie named `ragi_session` for the site. If cookies are blocked, you keep returning to the sign-in screen.
- Always use the same address for the site. Do not mix `http` and `https` or different host names: the cookie belongs to one site, and every change you make is checked to come from the same site.
- Extensions that block requests or remove browser headers can cause "Cross-site request blocked." or empty pages. Try a private window with extensions off.
- Press `/` anywhere (outside a text box) to jump to the search box. Press `Escape` to close a menu.
- On a phone, the left menu is behind the button **Open navigation**.
- **Export report** downloads a file named `rag-integrity-report` with the extension of the format you chose. If nothing downloads, check whether your browser blocked the download.
- The one-time API token dialog cannot be closed by clicking outside it or pressing `Escape`. Click **I've copied it**.
- A private window works but you must sign in each time.

## How to collect information for a bug report

Gather these before you ask for help. They let someone reproduce the problem without guessing.

1. **What you did and what you expected.** The page, the button, and what you saw instead. Copy the exact text of the message or toast.
2. **The version and mode.** The small card at the bottom of the left menu shows `LIVE` or `DEMO` and the version. **Settings**, **General** shows **Server mode** and **Version**.
3. **The time.** The date, the time and your time zone. Run details use your local time.
4. **The ids.**
   - For an audit: the run id. On the run's page in **Audit history**, click **Copy run id**.
   - For an issue: its address ends with `/issues/` and the issue id.
   - For a repair plan: the short id in its title; the full id is in the address (`plan=`).
   - For a document: its tenant and document id as shown on **Documents**.
5. **The test result.** For a connection problem, the whole result list of **Test connection** (copy the lines). Remove secrets first.
6. **The server's own answer.** `https://your-address/healthz` is public and shows whether the server is up, its version, its mode, whether the ledger is reachable and whether set-up is still required. For a failed action, the browser's developer tools (the **Network** tab) show the response; its `detail` field holds the message.
7. **Your browser and its version**, and a screenshot of the page.
8. **Whether it happens every time**, and whether a reload or a different browser changes it.

**Never include secrets.** Do not paste access keys, secret access keys, connection strings with passwords, Qdrant or API keys, signing secrets, webhook addresses, session cookies or API tokens. RAGGuard scrubs passwords out of its own messages, but check before you paste. An exported report lists document ids, so check that they are safe to share too.

## Related chapters

- [End-to-end journey](15-end-to-end-journey.md) and [Practical use cases](16-use-cases.md)
- [Reference: every value](17-reference.md)
- [Connect your data sources](04-data-sources.md), [Repair plans](08-repair-plans.md) and [Integrations](12-integrations.md)
- [Audit history](11-audit-history.md), [Alerts](13-alerts.md) and [Settings](14-settings.md)
