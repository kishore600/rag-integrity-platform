# Detect stale embeddings after a document changes

> When a source file changes but its chunks do not, your RAG app keeps answering from the old version. Store the file's hash on every chunk and compare.

## What goes wrong

You update a policy, a price list or a manual. Days later, users still get answers from the old text. The answer looks right and cites the right document, so nobody suspects the index.

## Why it happens

- The pipeline only processes new files, not changed ones.
- The change event was missed, or the re-embedding job failed halfway.
- The file was replaced in storage under the same name, and nothing noticed.

## How to check (pgvector)

Store the SHA-256 of the source file on every chunk when you embed it (`source_hash` here). Then find documents whose chunks were built from a different version than the file in storage today:

```sql
SELECT DISTINCT c.document_id
FROM chunks c
JOIN source_files s USING (document_id)
WHERE c.source_hash IS DISTINCT FROM s.sha256
ORDER BY c.document_id;
```

Every row is a document that is being answered from an older version. The examples use the tables described in the [guides introduction](README.md).

If your chunks carry no hash at all, add one now: without it, a changed file and an unchanged file look the same to any check.

**In Qdrant:** store the hash in each point's payload, scroll the collection with payloads only (no vectors, so it is fast) and compare each point's hash with the current file's hash.

## How to fix it

Re-embed the changed documents. Write the new chunks first, then delete the old ones by filter: `document_id` equal to the document and `source_hash` not equal to the new hash. Deleting first leaves a window where the document is missing.

## How to stop it happening again

- Trigger re-embedding on file changes, not only on new files.
- Run this check on a schedule; it is cheap because it reads hashes, not vectors.

RAGGuard runs this check, and seven others, read-only against S3 and Qdrant or pgvector: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
