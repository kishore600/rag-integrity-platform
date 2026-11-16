# Draft: making LangChain and LlamaIndex vector stores checkable

An article, not a docs pull request. As of November 2026 neither project takes docs pages for outside tools: LangChain lists only
published `langchain-*` packages, and LlamaIndex no longer accepts new integrations in its repository. LangChain's co-marketing
page asks for exactly this kind of content instead: "how to do ABC", not "how to use tool XYZ".

So: publish the text below as a blog post (dev.to, Medium or Hashnode), then share the link on X and LinkedIn, tagging LangChain and
LlamaIndex, and in their community forums. It is useful on its own: it explains which metadata to store so that any check,
RAGGuard's or your own, can tell whether the index matches the documents.

---

## Make your vector store checkable

When you add documents to a vector store, store a few extra metadata fields on every chunk. With them you can find stale, missing,
duplicate and half-indexed documents later, with a simple query or with a tool such as [RAGGuard](https://rag-integrity-platform.vercel.app).

| Field | Value |
|---|---|
| `document_id` | a stable ID for the source file, for example its path in your bucket |
| `source_hash` | the SHA-256 of the source file's bytes when you embedded it |
| `chunk_index` | 0, 1, 2 ... within the document |
| `chunk_total` | how many chunks the document was split into |
| `tenant_id` | the customer the document belongs to (multi-tenant apps) |

Also give every chunk a deterministic ID built from `document_id`, `source_hash` and `chunk_index`, so that re-running ingestion
overwrites chunks instead of adding duplicates.

### LangChain

```python
import hashlib
import uuid

from langchain_core.documents import Document

def chunk_documents(document_id: str, data: bytes, chunks: list[str], tenant_id: str) -> tuple[list[Document], list[str]]:
    source_hash = hashlib.sha256(data).hexdigest()
    docs, ids = [], []
    for i, text in enumerate(chunks):
        docs.append(Document(page_content=text, metadata={
            "document_id": document_id, "source_hash": source_hash,
            "chunk_index": i, "chunk_total": len(chunks), "tenant_id": tenant_id,
        }))
        ids.append(str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}|{source_hash}|{i}")))
    return docs, ids

# vector_store.add_documents(docs, ids=ids)
```

### LlamaIndex

Put the same fields in each node's `metadata`, and set the node ID the same way (`id_=...` when you create a `TextNode`).

### Check it

With pgvector, the metadata is in a JSON column; this finds documents with chunks from two versions of the file:

```sql
SELECT cmetadata->>'document_id' AS document_id,
       count(DISTINCT cmetadata->>'source_hash') AS versions
FROM langchain_pg_embedding
GROUP BY 1
HAVING count(DISTINCT cmetadata->>'source_hash') > 1;
```

The table and column names above are the ones LangChain's PGVector store uses by default; adjust them for your setup. More checks:
[rag-integrity-platform.vercel.app/guides](https://rag-integrity-platform.vercel.app/guides).
