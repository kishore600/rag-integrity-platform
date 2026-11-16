# List the RAGGuard MCP server

Publish `ragguard-cli` to PyPI first ([pypi.md](pypi.md)): the directories install it from there.

## The short description (use everywhere)

> **RAGGuard**: check that your RAG index matches your source documents. Finds documents missing from a Qdrant or pgvector index,
> stale embeddings, deleted documents that are still searchable, half-indexed documents, duplicate chunks and wrong-tenant chunks,
> with evidence and the recommended fix. Read-only.

Tools: `ragguard_status`, `ragguard_run_audit`, `ragguard_list_issues`, `ragguard_get_issue`, `ragguard_check_document`,
`ragguard_report`. Needs `RAGGUARD_API_KEY` (a RAGGuard API key, from the Integrations page). Optional `RAGGUARD_URL` for a
self-hosted server.

Install and run: `pip install "ragguard-cli[mcp]"`, command `ragguard`, argument `mcp` (stdio).

## The official MCP Registry

The registry (registry.modelcontextprotocol.io) is where MCP clients and other directories look first.

1. Install the publisher tool, `mcp-publisher`, following the registry's own "quickstart" guide.
2. In the repository folder: `mcp-publisher login github` (sign in as the GitHub account that owns the repository).
3. `mcp-publisher init`, then edit the generated `server.json`:
   - name: `io.github.kishore600/ragguard` (it must match the `mcp-name:` line in `clients/python/README.md`, which proves the PyPI
     package is yours)
   - package: registry type `pypi`, identifier `ragguard-cli`, the version you uploaded, transport `stdio`, a positional
     argument `mcp`
   - environment variables: `RAGGUARD_API_KEY` (required, secret) and `RAGGUARD_URL` (optional)
4. `mcp-publisher publish`. It validates the file and tells you what to fix.

## Other directories

Submit the short description and the GitHub link (https://github.com/kishore600/rag-integrity-platform, folder `clients/python`):

- Smithery (smithery.ai)
- Glama (glama.ai/mcp/servers)
- mcp.so
- PulseMCP (pulsemcp.com)

Each has its own submit form. Some also find servers on their own once the repository is public and the official registry lists it.
