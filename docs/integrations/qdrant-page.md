---
title: RAGGuard
short_description: "Check that a Qdrant collection still matches its source documents: missing, stale, deleted-but-searchable, duplicate and half-indexed points."
description: "Use RAGGuard to compare a Qdrant collection with the documents in S3 and find points that drifted: never indexed, built from an old version, deleted but still retrievable, duplicated or half-indexed."
---

# RAGGuard

[RAGGuard](https://rag-integrity-platform.vercel.app) checks that a Qdrant collection still matches the source documents it was
built from. It reads your documents in Amazon S3 (or any S3-compatible store) and your collection, and reports documents that were
never indexed, points built from an older version of a file, points whose source file was deleted but which can still be retrieved,
half-indexed documents, duplicate points from retried ingestion, empty or all-zero vectors, and points tagged with the wrong tenant.

## How it uses Qdrant

RAGGuard only reads: it scrolls the collection with payloads, retrieves points, and runs queries. It never writes, deletes or
changes your collection; fixes go to your own ingestion worker.

For the full checks, give each point a payload with:

| Field | Meaning |
|---|---|
| `document_id` | the source document the point came from |
| `source_hash` | the SHA-256 of the source file when it was embedded |
| `chunk_index`, `chunk_total` | the chunk's position and the number of chunks in the document |
| `tenant_id` | the customer it belongs to, in multi-tenant collections |

Your own field names work too: map them in RAGGuard. Create a keyword payload index on the document ID field, so per-document
checks do not scan the whole collection.

To check whether a deleted document can still be returned, RAGGuard runs a query using one of its leftover points as the query
vector; no embedding model is involved.

## Learn more

- [Guides](https://rag-integrity-platform.vercel.app/guides): each kind of drift, with a check you can run yourself
- [Command line tool and MCP server](https://github.com/kishore600/rag-integrity-platform/tree/main/clients/python)
