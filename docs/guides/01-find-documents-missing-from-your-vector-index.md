# Find documents missing from your vector index

> A file can sit in your bucket while nothing about it is searchable. Compare the documents in storage with the documents in your index to find them.

## What goes wrong

A user asks about a document that you know exists. The RAG app answers "I don't know" or answers from something else, and no error is shown anywhere. The file is in storage, but the index has no chunks for it.

## Why it happens

- The ingestion job never picked the file up (a missed event, a filter, a crash before it started).
- The pipeline recorded "success" before the vectors were written, and the write then failed.
- The file was uploaded under a name or prefix your pipeline does not watch.

## How to check (pgvector)

List every document in storage that has no chunk in the index:

```sql
SELECT s.document_id
FROM source_files s
LEFT JOIN (SELECT DISTINCT document_id FROM chunks) c USING (document_id)
WHERE c.document_id IS NULL
ORDER BY s.document_id;
```

Every row is a document your users cannot find. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** for each document ID in your bucket, count its points with a filter on the payload field that holds the document ID (for example `document_id`). A count of 0 means it is missing. Create a keyword payload index on that field first, or every count scans the whole collection.

## How to fix it

Re-run those documents through your ingestion pipeline. Then run the check again to confirm the count is now above zero.

## How to stop it happening again

- Mark a document as indexed only after reading the index back: count its chunks and compare with what you wrote.
- Run this check after every ingestion run and alert when it returns anything.

RAGGuard runs this check, and seven others, read-only against S3 and Qdrant or pgvector: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
