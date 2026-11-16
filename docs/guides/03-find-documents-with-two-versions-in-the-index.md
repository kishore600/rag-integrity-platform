# Find documents with two versions in the index

> The new version of a document was indexed, but the old chunks were never deleted, so both versions answer questions. Count the distinct versions per document.

## What goes wrong

Users get contradictory answers about the same document, or a confident answer from last quarter's version. The new chunks are in the index, so a quick spot check looks fine. The old chunks are there too, and they still rank.

## Why it happens

- The pipeline writes the new chunks and then deletes the old ones, and the delete failed or timed out.
- The old chunks had different IDs, so writing the new ones did not overwrite them.
- A re-index ran with a new chunker and kept the previous run's chunks.

## How to check (pgvector)

List documents whose chunks come from more than one version of the source file:

```sql
SELECT document_id, count(DISTINCT source_hash) AS versions
FROM chunks
GROUP BY document_id
HAVING count(DISTINCT source_hash) > 1
ORDER BY document_id;
```

Every row is a document where old and new content both answer. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** scroll with payloads only and group the points by document ID; any document with more than one distinct hash has two versions live.

## How to fix it

Keep only the chunks whose hash matches the current file, and delete the rest:

```sql
DELETE FROM chunks c
USING source_files s
WHERE c.document_id = s.document_id
  AND c.source_hash IS DISTINCT FROM s.sha256;
```

Run the check again: it should return nothing.

## How to stop it happening again

- Build chunk IDs from the document ID, the content hash and the chunk index, so a retry overwrites instead of adding.
- After each re-index, delete by filter (same document, different hash) and verify the old chunks are gone.

This is the most dangerous kind of drift, because the wrong answer comes with a real citation. RAGGuard checks for it on every audit: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
