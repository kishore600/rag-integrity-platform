# Guides: keep your RAG index in sync with your source documents

> Eight silent ways a RAG index drifts away from its source documents, with a copy-paste check for each: SQL for pgvector, and the same idea for Qdrant.

A RAG system answers from its index, not from your documents. When the two disagree, nothing crashes: ingestion jobs report success, dashboards stay green, and users get answers that are incomplete, out of date, or about content that was deleted. These guides show how to find each kind of drift yourself.

## The examples assume this layout

Every SQL example uses two tables. Rename the columns to match yours; if your metadata lives in a JSON column (LangChain and LlamaIndex do this), write `metadata->>'document_id'` instead of `document_id`.

```sql
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
```

Fill `source_files` from your storage: list the bucket, and take each file's SHA-256 from its object metadata (store it there at upload time) or compute it. An S3 ETag is not a reliable hash: for multipart uploads it is not the MD5 of the file.

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
