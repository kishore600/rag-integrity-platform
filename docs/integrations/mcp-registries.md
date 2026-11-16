# List the RAGGuard MCP server

Publish `ragguard-cli` to PyPI first ([pypi.md](pypi.md)): the registry checks that the package exists, and directories install it
from there. Every install of `ragguard-cli` includes the MCP server; MCP clients start it with `uvx ragguard-cli mcp`.

## The short description (use everywhere)

> **RAGGuard**: check that your RAG index matches your source documents. Finds documents missing from a Qdrant or pgvector index,
> stale embeddings, deleted documents that are still searchable, half-indexed documents, duplicate chunks and wrong-tenant chunks,
> with evidence and the recommended fix. Read-only.

Tools: `ragguard_status`, `ragguard_run_audit`, `ragguard_list_issues`, `ragguard_get_issue`, `ragguard_check_document`,
`ragguard_report`. Needs `RAGGUARD_API_KEY` (a RAGGuard API key, from the Integrations page). Optional `RAGGUARD_URL` for a
self-hosted server.

Install and run: `pip install ragguard-cli`, then `ragguard mcp` (stdio); or, without installing, `uvx ragguard-cli mcp`.

## The official MCP Registry

The registry (registry.modelcontextprotocol.io) is where MCP clients and other directories look first. The file it needs,
[server.json](../../server.json), is ready at the top of the repository. Its `name` matches the `mcp-name:` line in
`clients/python/README.md`, which is how the registry knows the PyPI package is yours. Its `version` must equal the version on PyPI.

In PowerShell, in the repository folder:

1. Download the publisher tool (the registry's own command for Windows):

   ```powershell
   $arch = if ([System.Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture -eq "Arm64") { "arm64" } else { "amd64" }; Invoke-WebRequest -Uri "https://github.com/modelcontextprotocol/registry/releases/latest/download/mcp-publisher_windows_$arch.tar.gz" -OutFile "mcp-publisher.tar.gz"; tar xf mcp-publisher.tar.gz mcp-publisher.exe; rm mcp-publisher.tar.gz
   ```

2. `.\mcp-publisher.exe login github`: open https://github.com/login/device, type the code it shows, and approve. Sign in as the
   GitHub account that owns the repository (`kishore600`).
3. `.\mcp-publisher.exe publish`: it checks `server.json` and the PyPI package, then prints "Successfully published". If it says
   the package cannot be found, wait two minutes after the PyPI upload and run it again.
4. Check: https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.kishore600/ragguard
5. Delete the tool from the folder so it is never committed: `Remove-Item .\mcp-publisher.exe`.

For a new version: upload it to PyPI, change both `version` fields in `server.json`, and publish again.

## Other directories (checked 16 November 2026)

- **Glama** (glama.ai/mcp/servers): the "Add Server" button; give it the GitHub link. Glama also finds public servers on its own.
- **mcp.so** (mcp.so/submit): type "MCP Server", the repository URL https://github.com/kishore600/rag-integrity-platform and the
  name RAGGuard. The free submission is enough; the $39 option only skips the wait.
- **PulseMCP**: not taking submissions right now. It says it picks servers up from the official registry, so the registry step
  above covers it.
- **Smithery**: now part of Arcade; its old publishing pages are gone. Check smithery.ai again later.
