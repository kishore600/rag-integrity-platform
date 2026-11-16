# Find half-indexed documents

> An ingestion worker can die after writing only some of a document's chunks. Store the expected chunk count on every chunk and look for gaps.

## What goes wrong

Questions about the first part of a long document work. Questions about the rest get "I don't know" or a vague answer. The document is in the index, so a check that only asks "is this document indexed?" says yes.

## Why it happens

- The worker was killed, timed out or ran out of memory partway through a document.
- A batch write was partly rejected (a rate limit, a payload too large) and the error was swallowed.
- A retry wrote the first chunks again but never reached the end.

## How to check (pgvector)

When you write chunks, store each one's position (`chunk_index`) and the number of chunks the document should have (`chunk_total`). Then list documents with fewer chunks than expected:

```sql
SELECT document_id,
       max(chunk_total)            AS expected,
       count(DISTINCT chunk_index) AS present
FROM chunks
GROUP BY document_id
HAVING count(DISTINCT chunk_index) < max(chunk_total)
ORDER BY document_id;
```

Every row is a document that is only partly searchable. The examples use the tables described in the [guides introduction](README.md).

Without a stored total you can still spot some gaps: a document whose highest `chunk_index` is larger than its number of chunks minus one is missing chunks in the middle. A missing tail cannot be seen that way, which is why the total matters.

**In Qdrant:** store `chunk_index` and `chunk_total` in the payload, scroll with payloads only, and count the distinct indexes per document.

## How to fix it

Re-index the affected documents. If your chunking is deterministic, you can write only the missing chunks.

## How to stop it happening again

- Mark a document done only after counting its chunks in the index and comparing with the total.
- Alert when this check returns anything after an ingestion run.

RAGGuard finds partly indexed documents on every audit, from the chunk total or from gaps in the numbering: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
