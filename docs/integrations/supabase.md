# Draft: a Supabase integrations listing

Supabase lists partner tools on its integrations pages; apply through the partner form linked from supabase.com/partners. The
form asks for a name, a short and a long description, a category, a website and screenshots. Use the text below.

---

**Name:** RAGGuard

**Category:** AI / Vector

**Short description (one line):**
Check that your pgvector index on Supabase still matches your source documents.

**Long description:**
RAGGuard compares the files in your storage (Supabase Storage through its S3 endpoint, or Amazon S3) with the vectors in your
pgvector table, and finds what drifted silently: documents that were never embedded, embeddings built from an old version of a file,
deleted documents that are still searchable, half-indexed documents, duplicate chunks, empty vectors and rows tagged with the wrong
tenant. Each finding shows its evidence and a safe fix that your own worker carries out.

RAGGuard only reads your database: every query runs in a read-only transaction, so a read-only database role is enough. It works
with your own table and column names, including the tables LangChain and LlamaIndex create, where the metadata lives in a JSON column.

**Website:** https://rag-integrity-platform.vercel.app

**Documentation:** https://rag-integrity-platform.vercel.app/guides

**Screenshots:** the Overview page, an issue with its evidence, and the Data Sources page with the pgvector card (take them from a
demo workspace, never from real customer data).
