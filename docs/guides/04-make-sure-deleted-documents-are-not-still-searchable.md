# Make sure deleted documents are not still searchable

> Deleting a file from storage does not delete its vectors. Find chunks whose source file no longer exists, then prove whether a search can still return them.

## What goes wrong

A document is withdrawn: an outdated contract, a recalled manual, a file a user asked you to erase. It is gone from storage, but the RAG app keeps quoting it. If the deletion was a legal request, the data is not actually deleted.

## Why it happens

- Deleting the file does not trigger anything in the index.
- The cleanup job only handles new and changed files.
- The delete ran against the wrong collection or tenant.

## How to check (pgvector)

List documents that still have chunks but no longer exist in storage:

```sql
SELECT c.document_id, count(*) AS chunks
FROM chunks c
LEFT JOIN source_files s USING (document_id)
WHERE s.document_id IS NULL
GROUP BY c.document_id
ORDER BY c.document_id;
```

Then prove the content can really be returned: search with one of the document's own stored vectors and see whether it comes back near the top.

```sql
SELECT id, document_id
FROM chunks
ORDER BY embedding <=> (SELECT embedding FROM chunks WHERE document_id = 'deleted-doc.pdf' LIMIT 1)
LIMIT 5;
```

Replace `deleted-doc.pdf` with a document ID from the first query. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** compare the document IDs in your payloads with your bucket listing, then run a query using one of the leftover points as the query (Qdrant's query API accepts a point ID).

## How to fix it

Delete the chunks by document ID, then run both queries again: the first should return nothing, and the second should no longer return the deleted document.

## How to stop it happening again

- Treat a deletion in storage as an event your pipeline must handle, like an upload.
- For erasure requests, keep a record of the check showing the content can no longer be retrieved.

RAGGuard checks deletions on every audit and can prove a removed document no longer comes back in search: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
