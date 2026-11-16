# Find empty or all-zero vectors

> A failed embedding call can leave a chunk with no vector or a vector of zeros. Such a chunk can never be found by search. Check the vector's length.

## What goes wrong

Part of a document is never returned, however closely a question matches it. The chunk exists and its text is right, so it looks fine when you inspect it, but its vector carries no meaning.

## Why it happens

- The embedding API returned an error or an empty result, and the code wrote a placeholder instead of failing.
- A default value (a zero vector) was used for chunks whose text was empty after cleaning.
- A migration or copy lost the vectors but kept the rows.

## How to check (pgvector)

List chunks with no vector or a vector whose length (norm) is zero:

```sql
SELECT id, document_id, chunk_index
FROM chunks
WHERE embedding IS NULL
   OR vector_norm(embedding) = 0
ORDER BY document_id, chunk_index;
```

`vector_norm` is part of pgvector. Every row is a chunk that search cannot reach. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** scroll with vectors included and check each vector's norm in your code. This reads every vector, so run it in batches or on a schedule rather than on every request.

## How to fix it

Re-embed the affected chunks, or the whole document if many are affected. Check that the text of each chunk is not empty first: an empty chunk should be dropped, not embedded.

## How to stop it happening again

- Fail the ingestion job when an embedding call fails; never write a placeholder vector.
- Reject vectors whose norm is zero before writing them.

RAGGuard can check for empty and all-zero vectors on every audit: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
