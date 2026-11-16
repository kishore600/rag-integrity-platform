import{aF as w,j as n,E as y,b8 as k,A as c,L as v,r as x,C as b}from"./index-Cumod1Z4.js";import{G as u}from"./markdown-DlKrFFUl.js";import{A as _}from"./contact-CKkU_yhU.js";import{A}from"./arrow-right-Bm47vB1c.js";import{M as R}from"./mail-eDmtOh0r.js";import"./copy-button-BGYhqcQ2.js";import"./check-BiQtOUGC.js";import"./copy-BQcb_5hh.js";import"./prose-CAc7TcVg.js";import"./help-media-Dg-9isLl.js";const E=`# Find documents missing from your vector index

> A file can sit in your bucket while nothing about it is searchable. Compare the documents in storage with the documents in your index to find them.

## What goes wrong

A user asks about a document that you know exists. The RAG app answers "I don't know" or answers from something else, and no error is shown anywhere. The file is in storage, but the index has no chunks for it.

## Why it happens

- The ingestion job never picked the file up (a missed event, a filter, a crash before it started).
- The pipeline recorded "success" before the vectors were written, and the write then failed.
- The file was uploaded under a name or prefix your pipeline does not watch.

## How to check (pgvector)

List every document in storage that has no chunk in the index:

\`\`\`sql
SELECT s.document_id
FROM source_files s
LEFT JOIN (SELECT DISTINCT document_id FROM chunks) c USING (document_id)
WHERE c.document_id IS NULL
ORDER BY s.document_id;
\`\`\`

Every row is a document your users cannot find. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** for each document ID in your bucket, count its points with a filter on the payload field that holds the document ID (for example \`document_id\`). A count of 0 means it is missing. Create a keyword payload index on that field first, or every count scans the whole collection.

## How to fix it

Re-run those documents through your ingestion pipeline. Then run the check again to confirm the count is now above zero.

## How to stop it happening again

- Mark a document as indexed only after reading the index back: count its chunks and compare with what you wrote.
- Run this check after every ingestion run and alert when it returns anything.

RAGGuard runs this check, and seven others, read-only against S3 and Qdrant or pgvector: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,I=`# Detect stale embeddings after a document changes

> When a source file changes but its chunks do not, your RAG app keeps answering from the old version. Store the file's hash on every chunk and compare.

## What goes wrong

You update a policy, a price list or a manual. Days later, users still get answers from the old text. The answer looks right and cites the right document, so nobody suspects the index.

## Why it happens

- The pipeline only processes new files, not changed ones.
- The change event was missed, or the re-embedding job failed halfway.
- The file was replaced in storage under the same name, and nothing noticed.

## How to check (pgvector)

Store the SHA-256 of the source file on every chunk when you embed it (\`source_hash\` here). Then find documents whose chunks were built from a different version than the file in storage today:

\`\`\`sql
SELECT DISTINCT c.document_id
FROM chunks c
JOIN source_files s USING (document_id)
WHERE c.source_hash IS DISTINCT FROM s.sha256
ORDER BY c.document_id;
\`\`\`

Every row is a document that is being answered from an older version. The examples use the tables described in the [guides introduction](README.md).

If your chunks carry no hash at all, add one now: without it, a changed file and an unchanged file look the same to any check.

**In Qdrant:** store the hash in each point's payload, scroll the collection with payloads only (no vectors, so it is fast) and compare each point's hash with the current file's hash.

## How to fix it

Re-embed the changed documents. Write the new chunks first, then delete the old ones by filter: \`document_id\` equal to the document and \`source_hash\` not equal to the new hash. Deleting first leaves a window where the document is missing.

## How to stop it happening again

- Trigger re-embedding on file changes, not only on new files.
- Run this check on a schedule; it is cheap because it reads hashes, not vectors.

RAGGuard runs this check, and seven others, read-only against S3 and Qdrant or pgvector: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,T=`# Find documents with two versions in the index

> The new version of a document was indexed, but the old chunks were never deleted, so both versions answer questions. Count the distinct versions per document.

## What goes wrong

Users get contradictory answers about the same document, or a confident answer from last quarter's version. The new chunks are in the index, so a quick spot check looks fine. The old chunks are there too, and they still rank.

## Why it happens

- The pipeline writes the new chunks and then deletes the old ones, and the delete failed or timed out.
- The old chunks had different IDs, so writing the new ones did not overwrite them.
- A re-index ran with a new chunker and kept the previous run's chunks.

## How to check (pgvector)

List documents whose chunks come from more than one version of the source file:

\`\`\`sql
SELECT document_id, count(DISTINCT source_hash) AS versions
FROM chunks
GROUP BY document_id
HAVING count(DISTINCT source_hash) > 1
ORDER BY document_id;
\`\`\`

Every row is a document where old and new content both answer. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** scroll with payloads only and group the points by document ID; any document with more than one distinct hash has two versions live.

## How to fix it

Keep only the chunks whose hash matches the current file, and delete the rest:

\`\`\`sql
DELETE FROM chunks c
USING source_files s
WHERE c.document_id = s.document_id
  AND c.source_hash IS DISTINCT FROM s.sha256;
\`\`\`

Run the check again: it should return nothing.

## How to stop it happening again

- Build chunk IDs from the document ID, the content hash and the chunk index, so a retry overwrites instead of adding.
- After each re-index, delete by filter (same document, different hash) and verify the old chunks are gone.

This is the most dangerous kind of drift, because the wrong answer comes with a real citation. RAGGuard checks for it on every audit: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,G=`# Make sure deleted documents are not still searchable

> Deleting a file from storage does not delete its vectors. Find chunks whose source file no longer exists, then prove whether a search can still return them.

## What goes wrong

A document is withdrawn: an outdated contract, a recalled manual, a file a user asked you to erase. It is gone from storage, but the RAG app keeps quoting it. If the deletion was a legal request, the data is not actually deleted.

## Why it happens

- Deleting the file does not trigger anything in the index.
- The cleanup job only handles new and changed files.
- The delete ran against the wrong collection or tenant.

## How to check (pgvector)

List documents that still have chunks but no longer exist in storage:

\`\`\`sql
SELECT c.document_id, count(*) AS chunks
FROM chunks c
LEFT JOIN source_files s USING (document_id)
WHERE s.document_id IS NULL
GROUP BY c.document_id
ORDER BY c.document_id;
\`\`\`

Then prove the content can really be returned: search with one of the document's own stored vectors and see whether it comes back near the top.

\`\`\`sql
SELECT id, document_id
FROM chunks
ORDER BY embedding <=> (SELECT embedding FROM chunks WHERE document_id = 'deleted-doc.pdf' LIMIT 1)
LIMIT 5;
\`\`\`

Replace \`deleted-doc.pdf\` with a document ID from the first query. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** compare the document IDs in your payloads with your bucket listing, then run a query using one of the leftover points as the query (Qdrant's query API accepts a point ID).

## How to fix it

Delete the chunks by document ID, then run both queries again: the first should return nothing, and the second should no longer return the deleted document.

## How to stop it happening again

- Treat a deletion in storage as an event your pipeline must handle, like an upload.
- For erasure requests, keep a record of the check showing the content can no longer be retrieved.

RAGGuard checks deletions on every audit and can prove a removed document no longer comes back in search: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,D=`# Find half-indexed documents

> An ingestion worker can die after writing only some of a document's chunks. Store the expected chunk count on every chunk and look for gaps.

## What goes wrong

Questions about the first part of a long document work. Questions about the rest get "I don't know" or a vague answer. The document is in the index, so a check that only asks "is this document indexed?" says yes.

## Why it happens

- The worker was killed, timed out or ran out of memory partway through a document.
- A batch write was partly rejected (a rate limit, a payload too large) and the error was swallowed.
- A retry wrote the first chunks again but never reached the end.

## How to check (pgvector)

When you write chunks, store each one's position (\`chunk_index\`) and the number of chunks the document should have (\`chunk_total\`). Then list documents with fewer chunks than expected:

\`\`\`sql
SELECT document_id,
       max(chunk_total)            AS expected,
       count(DISTINCT chunk_index) AS present
FROM chunks
GROUP BY document_id
HAVING count(DISTINCT chunk_index) < max(chunk_total)
ORDER BY document_id;
\`\`\`

Every row is a document that is only partly searchable. The examples use the tables described in the [guides introduction](README.md).

Without a stored total you can still spot some gaps: a document whose highest \`chunk_index\` is larger than its number of chunks minus one is missing chunks in the middle. A missing tail cannot be seen that way, which is why the total matters.

**In Qdrant:** store \`chunk_index\` and \`chunk_total\` in the payload, scroll with payloads only, and count the distinct indexes per document.

## How to fix it

Re-index the affected documents. If your chunking is deterministic, you can write only the missing chunks.

## How to stop it happening again

- Mark a document done only after counting its chunks in the index and comparing with the total.
- Alert when this check returns anything after an ingestion run.

RAGGuard finds partly indexed documents on every audit, from the chunk total or from gaps in the numbering: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,S=`# Find duplicate chunks from retried ingestion

> A retried ingestion job can write the same chunk twice. Duplicates crowd other content out of the top results and skew answers. Group by document and position to find them.

## What goes wrong

The same passage fills several of the top results, so the answer is built from one repeated piece instead of several different ones. Index size and cost also grow for no reason.

## Why it happens

- The chunk ID was random (a fresh UUID each time), so a retry inserted new rows instead of overwriting.
- Two workers processed the same document at the same time.
- A re-index ran without first removing the previous run.

## How to check (pgvector)

List every position that holds more than one chunk:

\`\`\`sql
SELECT document_id, chunk_index, count(*) AS copies
FROM chunks
GROUP BY document_id, chunk_index
HAVING count(*) > 1
ORDER BY document_id, chunk_index;
\`\`\`

If a document also has [two versions in the index](03-find-documents-with-two-versions-in-the-index.md), its chunks show up here too. Fix the versions first. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** scroll with payloads only and group points by document ID and chunk index; any group with more than one point is a duplicate.

## How to fix it

Keep one row per position and delete the others:

\`\`\`sql
DELETE FROM chunks a
USING chunks b
WHERE a.document_id = b.document_id
  AND a.chunk_index = b.chunk_index
  AND a.source_hash IS NOT DISTINCT FROM b.source_hash
  AND a.id > b.id;
\`\`\`

## How to stop it happening again

Make chunk IDs deterministic: build them from the document ID, the content hash and the chunk index (for example a UUID v5 of those values). A retry then overwrites the same rows instead of adding new ones.

RAGGuard finds duplicate chunks on every audit: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,C=`# Find empty or all-zero vectors

> A failed embedding call can leave a chunk with no vector or a vector of zeros. Such a chunk can never be found by search. Check the vector's length.

## What goes wrong

Part of a document is never returned, however closely a question matches it. The chunk exists and its text is right, so it looks fine when you inspect it, but its vector carries no meaning.

## Why it happens

- The embedding API returned an error or an empty result, and the code wrote a placeholder instead of failing.
- A default value (a zero vector) was used for chunks whose text was empty after cleaning.
- A migration or copy lost the vectors but kept the rows.

## How to check (pgvector)

List chunks with no vector or a vector whose length (norm) is zero:

\`\`\`sql
SELECT id, document_id, chunk_index
FROM chunks
WHERE embedding IS NULL
   OR vector_norm(embedding) = 0
ORDER BY document_id, chunk_index;
\`\`\`

\`vector_norm\` is part of pgvector. Every row is a chunk that search cannot reach. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** scroll with vectors included and check each vector's norm in your code. This reads every vector, so run it in batches or on a schedule rather than on every request.

## How to fix it

Re-embed the affected chunks, or the whole document if many are affected. Check that the text of each chunk is not empty first: an empty chunk should be dropped, not embedded.

## How to stop it happening again

- Fail the ingestion job when an embedding call fails; never write a placeholder vector.
- Reject vectors whose norm is zero before writing them.

RAGGuard can check for empty and all-zero vectors on every audit: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,M=`# Catch chunks tagged with the wrong tenant

> In a multi-tenant RAG app, one chunk with the wrong tenant tag can show one customer's content to another. Compare every chunk's tenant with its source file's tenant.

## What goes wrong

Your app filters search results by tenant, so each customer only sees their own documents. If a chunk carries the wrong tenant tag, the filter lets it through to the wrong customer. Nothing errors, and the leak is only found when someone notices content that is not theirs.

## Why it happens

- The tenant was taken from the wrong field, or from a default, during ingestion.
- A document was moved between tenants in storage, and the index kept the old tag.
- A bulk re-index ran with the wrong tenant context.

## How to check (pgvector)

Give \`source_files\` the tenant each file belongs to (often the first folder of its path), then list chunks whose tag disagrees:

\`\`\`sql
SELECT c.id, c.document_id, c.tenant_id AS chunk_tenant, s.tenant_id AS source_tenant
FROM chunks c
JOIN source_files s USING (document_id)
WHERE c.tenant_id IS DISTINCT FROM s.tenant_id
ORDER BY c.document_id, c.id;
\`\`\`

Every row is a chunk that can be shown to the wrong customer. Chunks with no tenant at all appear too, because a missing tag is just as unsafe. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** scroll with payloads only and compare each point's tenant field with the tenant of its source file.

## How to fix it

Correct the tenant tag on those chunks, or delete and re-index them. Treat it as a security incident: check your logs for whether the chunks were returned to another tenant.

## How to stop it happening again

- Derive the tenant from the file's location in one place in your pipeline, never from a default.
- Run this check after every ingestion run, and alert on any result.

RAGGuard checks tenant tags on every audit and shows an isolation report per customer: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,N=`# Use RAGGuard from your AI assistant

> Let Claude Code, Cursor, Copilot or any MCP-capable assistant check your RAG index for you: a rule to paste into your project, an MCP server, and a command your assistant can run.

If an AI assistant writes or changes your ingestion code, it should also check that the index is still right afterwards. RAGGuard gives it three ways to do that.

## 1. Add a rule to your project

Paste this into your assistant's rules file: \`AGENTS.md\`, \`CLAUDE.md\`, \`.cursorrules\`, \`.github/copilot-instructions.md\` or similar.

\`\`\`markdown
## RAG index integrity (RAGGuard)
- After changing ingestion, chunking or embedding code, or after a bulk re-index, run
  \`ragguard check --fail-on high\` (or the MCP tool \`ragguard_run_audit\`) and fix every open
  issue it reports before saying the work is done.
- Do not call an ingestion change finished while RAGGuard reports missing, stale, duplicate,
  half-indexed or wrong-tenant chunks.
- When a user reports a wrong or outdated answer, run \`ragguard document <document-id>\`
  before changing prompts or models: the index is often the cause.
\`\`\`

## 2. Install the command and get an API key

\`\`\`bash
pip install "ragguard-cli[mcp] @ git+https://github.com/kishore600/rag-integrity-platform#subdirectory=clients/python"
\`\`\`

Create an API key in RAGGuard on the **Integrations** page, then set it where your assistant runs:

\`\`\`bash
export RAGGUARD_API_KEY=ragi_your_key_here
\`\`\`

The key can run audits and read results. It cannot read your connection settings or create other keys.

## 3. Connect the MCP server

**Claude Code:**

\`\`\`bash
claude mcp add ragguard -e RAGGUARD_API_KEY=ragi_your_key_here -- ragguard mcp
\`\`\`

**Cursor** (\`.cursor/mcp.json\`), **Claude Desktop** and other MCP clients:

\`\`\`json
{
  "mcpServers": {
    "ragguard": {
      "command": "ragguard",
      "args": ["mcp"],
      "env": { "RAGGUARD_API_KEY": "ragi_your_key_here" }
    }
  }
}
\`\`\`

Your assistant then has these tools:

| Tool | What it does |
|---|---|
| \`ragguard_status\` | The health score, document and issue counts, and the latest audit |
| \`ragguard_run_audit\` | Runs an audit, waits for it to finish and returns the summary |
| \`ragguard_list_issues\` | The open issues, most severe first, optionally by severity |
| \`ragguard_get_issue\` | One issue with its evidence and the recommended fix |
| \`ragguard_check_document\` | Everything RAGGuard knows about one document |
| \`ragguard_report\` | The full audit report as Markdown |

Then ask: "Is my RAG index in sync?" or "Why does the bot still quote the old refund policy?"

## 4. Or use the command directly

\`\`\`bash
ragguard check --fail-on high   # run an audit; exit code 1 if open issues are high or critical
ragguard status                 # the latest results, without running an audit
ragguard issues --severity high # open issues
ragguard document refund-policy.pdf
\`\`\`

\`ragguard check\` works in CI too: add it after your ingestion job, and the job fails when the index drifts.

Not using RAGGuard yet? [Create a workspace](https://rag-integrity-platform.vercel.app/signup), connect your bucket and your Qdrant or pgvector index, and create the API key. It is free during the beta.
`,L=`# Guides: keep your RAG index in sync with your source documents

> Eight silent ways a RAG index drifts away from its source documents, with a copy-paste check for each: SQL for pgvector, and the same idea for Qdrant.

A RAG system answers from its index, not from your documents. When the two disagree, nothing crashes: ingestion jobs report success, dashboards stay green, and users get answers that are incomplete, out of date, or about content that was deleted. These guides show how to find each kind of drift yourself.

## The examples assume this layout

Every SQL example uses two tables. Rename the columns to match yours; if your metadata lives in a JSON column (LangChain and LlamaIndex do this), write \`metadata->>'document_id'\` instead of \`document_id\`.

\`\`\`sql
-- your vector table (pgvector): one row per chunk
CREATE TABLE chunks (
  id          bigserial PRIMARY KEY,
  document_id text NOT NULL,   -- which source file the chunk came from
  chunk_index int  NOT NULL,   -- 0, 1, 2 ... within the document
  chunk_total int,             -- how many chunks the document should have
  source_hash text,            -- SHA-256 of the source file when it was embedded
  tenant_id   text,            -- which customer it belongs to (multi-tenant apps)
  embedding   vector(1536)
);

-- the files that exist right now, from a listing of your bucket
CREATE TABLE source_files (
  document_id text PRIMARY KEY,
  sha256      text NOT NULL,   -- SHA-256 of the current file
  tenant_id   text
);
\`\`\`

Fill \`source_files\` from your storage: list the bucket, and take each file's SHA-256 from its object metadata (store it there at upload time) or compute it. An S3 ETag is not a reliable hash: for multipart uploads it is not the MD5 of the file.

## The guides

1. [Find documents missing from your vector index](01-find-documents-missing-from-your-vector-index.md)
2. [Detect stale embeddings after a document changes](02-detect-stale-embeddings-after-a-document-changes.md)
3. [Find documents with two versions in the index](03-find-documents-with-two-versions-in-the-index.md)
4. [Make sure deleted documents are not still searchable](04-make-sure-deleted-documents-are-not-still-searchable.md)
5. [Find half-indexed documents](05-find-half-indexed-documents.md)
6. [Find duplicate chunks from retried ingestion](06-find-duplicate-chunks-from-retried-ingestion.md)
7. [Find empty or all-zero vectors](07-find-empty-or-all-zero-vectors.md)
8. [Catch chunks tagged with the wrong tenant](08-catch-chunks-tagged-with-the-wrong-tenant.md)

Using an AI coding assistant? See [Use RAGGuard from your AI assistant](09-use-ragguard-from-your-ai-assistant.md).

## Which check first

Start with [two versions in the index](03-find-documents-with-two-versions-in-the-index.md) and [deleted documents](04-make-sure-deleted-documents-are-not-still-searchable.md). They are the hardest to notice: the answers sound confident and cite a real document, but come from content that should no longer be there.

RAGGuard runs all eight checks for you, read-only, against S3 and Qdrant or pgvector: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
`,O=Object.assign({"../../../../docs/guides/01-find-documents-missing-from-your-vector-index.md":E,"../../../../docs/guides/02-detect-stale-embeddings-after-a-document-changes.md":I,"../../../../docs/guides/03-find-documents-with-two-versions-in-the-index.md":T,"../../../../docs/guides/04-make-sure-deleted-documents-are-not-still-searchable.md":G,"../../../../docs/guides/05-find-half-indexed-documents.md":D,"../../../../docs/guides/06-find-duplicate-chunks-from-retried-ingestion.md":S,"../../../../docs/guides/07-find-empty-or-all-zero-vectors.md":C,"../../../../docs/guides/08-catch-chunks-tagged-with-the-wrong-tenant.md":M,"../../../../docs/guides/09-use-ragguard-from-your-ai-assistant.md":N,"../../../../docs/guides/README.md":L}),r=e=>e.replace(/^.*\//,"").replace(/\.md$/,"");function l(e,t){var o,a;const s=r(e);return{file:s,slug:s.replace(/^\d+-/,""),title:((o=/^#\s+(.+?)\s*$/m.exec(t))==null?void 0:o[1])??s,summary:((a=/^>\s+(.+?)\s*$/m.exec(t))==null?void 0:a[1])??"",text:t}}const m=Object.entries(O).sort(([e],[t])=>e.localeCompare(t)),i=m.filter(([e])=>r(e)!=="README").map(([e,t])=>l(e,t));var h;const d=l("README.md",((h=m.find(([e])=>r(e)==="README"))==null?void 0:h[1])??"# Guides"),H=new Map(i.map(e=>[e.slug,e])),j=new Map(i.map(e=>[e.file,e]));function g(e){if(e.startsWith("#"))return{native:e};if(/^(https?:|mailto:)/i.test(e))return{external:e};if(e.startsWith("/"))return{to:e};const[t,s]=e.split("#"),o=s?`#${s}`:"";if(t==="README.md")return{to:`/guides${o}`};const a=j.get(t.replace(/\.md$/,""));return a?{to:`/guides/${a.slug}${o}`}:{unavailable:!0}}function p(e){x.useEffect(()=>{const t=document.title;return document.title=`${e} · RAGGuard`,()=>{document.title=t}},[e])}function f(){return n.jsxs(b,{className:"mt-12 max-w-3xl p-6",children:[n.jsx("h2",{className:"text-section text-ink",children:"Check all of this automatically"}),n.jsx("p",{className:"mt-1.5 text-body text-ink-2",children:"RAGGuard runs every check in these guides against your S3 bucket and your Qdrant or pgvector index, read-only, and shows the evidence and a safe fix for each problem. It is free during the beta."}),n.jsxs("div",{className:"mt-4 flex flex-wrap gap-3",children:[n.jsxs(c,{variant:"primary",to:"/signup",children:["Create your workspace ",n.jsx(A,{className:"h-4 w-4","aria-hidden":!0})]}),n.jsxs("a",{href:_,className:"inline-flex h-9 items-center gap-2 rounded-control border border-line bg-workspace px-3.5 text-body font-medium text-ink hover:bg-surface",children:[n.jsx(R,{className:"h-4 w-4","aria-hidden":!0})," Book a free audit"]})]})]})}function K(){return p(d.title),n.jsxs("div",{className:"mx-auto max-w-3xl py-4",children:[n.jsx(u,{text:d.text,resolveHref:g}),n.jsx(f,{})]})}function J(){const{slug:e=""}=w(),t=H.get(e);if(p((t==null?void 0:t.title)??"Guide not found"),!t)return n.jsx(y,{icon:k,title:"That guide doesn't exist",description:"The address doesn't match one of the guides.",action:n.jsx(c,{variant:"primary",to:"/guides",children:"All guides"})});const s=i.filter(o=>o.slug!==e);return n.jsxs("div",{className:"mx-auto max-w-3xl py-4",children:[n.jsx(u,{text:t.text,resolveHref:g}),n.jsx(f,{}),n.jsxs("nav",{"aria-label":"Other guides",className:"mt-12 max-w-3xl border-t border-line pt-6",children:[n.jsx("h2",{className:"text-section text-ink",children:"More guides"}),n.jsx("ul",{className:"mt-3 space-y-2",children:s.map(o=>n.jsx("li",{children:n.jsx(v,{to:`/guides/${o.slug}`,className:"text-body font-medium text-brand hover:text-brand-hover hover:underline",children:o.title})},o.slug))})]})]})}export{i as GUIDES,d as GUIDES_README,J as GuidePage,K as GuidesIndex,g as resolveGuideHref};
