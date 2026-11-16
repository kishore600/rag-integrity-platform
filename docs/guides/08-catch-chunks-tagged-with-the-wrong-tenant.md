# Catch chunks tagged with the wrong tenant

> In a multi-tenant RAG app, one chunk with the wrong tenant tag can show one customer's content to another. Compare every chunk's tenant with its source file's tenant.

## What goes wrong

Your app filters search results by tenant, so each customer only sees their own documents. If a chunk carries the wrong tenant tag, the filter lets it through to the wrong customer. Nothing errors, and the leak is only found when someone notices content that is not theirs.

## Why it happens

- The tenant was taken from the wrong field, or from a default, during ingestion.
- A document was moved between tenants in storage, and the index kept the old tag.
- A bulk re-index ran with the wrong tenant context.

## How to check (pgvector)

Give `source_files` the tenant each file belongs to (often the first folder of its path), then list chunks whose tag disagrees:

```sql
SELECT c.id, c.document_id, c.tenant_id AS chunk_tenant, s.tenant_id AS source_tenant
FROM chunks c
JOIN source_files s USING (document_id)
WHERE c.tenant_id IS DISTINCT FROM s.tenant_id
ORDER BY c.document_id, c.id;
```

Every row is a chunk that can be shown to the wrong customer. Chunks with no tenant at all appear too, because a missing tag is just as unsafe. The examples use the tables described in the [guides introduction](README.md).

**In Qdrant:** scroll with payloads only and compare each point's tenant field with the tenant of its source file.

## How to fix it

Correct the tenant tag on those chunks, or delete and re-index them. Treat it as a security incident: check your logs for whether the chunks were returned to another tenant.

## How to stop it happening again

- Derive the tenant from the file's location in one place in your pipeline, never from a default.
- Run this check after every ingestion run, and alert on any result.

RAGGuard checks tenant tags on every audit and shows an isolation report per customer: [rag-integrity-platform.vercel.app](https://rag-integrity-platform.vercel.app).
