# Find duplicate chunks from retried ingestion

> A retried ingestion job can write the same chunk twice. Duplicates crowd other content out of the top results and skew answers. Group by document and position to find them.

## What goes wrong

The same passage fills several of the top results, so the answer is built from one repeated piece instead of several different ones. Index size and cost also grow for no reason.

## Why it happens

- The chunk ID was random (a fresh UUID each time), so a retry inserted new rows instead of overwriting.
- Two workers processed the same document at the same time.
- A re-index ran without first removing the previous run.

## How to check (pgvector)

List every position that holds more than one chunk:

```sql
SELECT document_id, chunk_index, count(*) AS copies
FROM chunks
GROUP BY document_id, chunk_index
HAVING count(*) > 1
ORDER BY document_id, chunk_index;
```

If a document also has [two versions in the index](03-find-documents-with-two-versions-in-the-index.md), its chunks show up here too. Fix the versions first. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** scroll with payloads only and group points by document ID and chunk index; any group with more than one point is a duplicate.

## How to fix it

Keep one row per position and delete the others:

```sql
DELETE FROM chunks a
USING chunks b
WHERE a.document_id = b.document_id
  AND a.chunk_index = b.chunk_index
  AND a.source_hash IS NOT DISTINCT FROM b.source_hash
  AND a.id > b.id;
```

## How to stop it happening again

Make chunk IDs deterministic: build them from the document ID, the content hash and the chunk index (for example a UUID v5 of those values). A retry then overwrites the same rows instead of adding new ones.

RAGGuard finds duplicate chunks on every audit: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
