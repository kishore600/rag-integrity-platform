# ragguard-cli

Check that your RAG index matches your source documents, from a terminal, a CI job or an AI assistant.

[RAGGuard](https://rag-integrity-platform.vercel.app) compares the files in Amazon S3 with your Qdrant or pgvector index, and
optionally your ingestion pipeline's records, and finds what silently drifted: documents that were never embedded, stale embeddings
after a document changed, two versions of a document answering at once, deleted documents that are still searchable, half-indexed
documents, duplicate chunks, empty vectors and chunks tagged with the wrong tenant. It only reads your systems.

This package gives you:

- the `ragguard` command, for people and CI jobs;
- an MCP server (`ragguard mcp`), so Claude Code, Cursor, Claude Desktop, VS Code and other AI assistants can run the checks.

<!-- mcp-name: io.github.kishore600/ragguard -->

## Install

```bash
pip install "ragguard-cli[mcp]"     # or without [mcp] if you only need the command
```

Create an API key in RAGGuard on the **Integrations** page and set it:

```bash
export RAGGUARD_API_KEY=ragi_your_key_here
# export RAGGUARD_URL=https://your-own-ragguard.example.com   # only for a self-hosted server
```

The key can run audits and read results. It cannot read your connection settings or create other keys.

## Use it

```bash
ragguard check --fail-on high    # run an audit and wait; exit code 1 if open issues are high or critical
ragguard status                  # the latest results, without running an audit
ragguard issues --severity high  # open issues, most severe first
ragguard issue ISSUE_ID          # one issue with its evidence and the recommended fix
ragguard document refund-policy.pdf
ragguard report > report.md
```

Add `--json` to `check`, `status`, `issues`, `issue` and `document` for machine-readable output. Exit codes: `0` fine, `1` open issues at
or above `--fail-on`, `2` an error.

### In CI

```yaml
- run: pip install ragguard-cli
- run: ragguard check --fail-on high
  env:
    RAGGUARD_API_KEY: ${{ secrets.RAGGUARD_API_KEY }}
```

## Connect your AI assistant (MCP)

**Claude Code:**

```bash
claude mcp add ragguard -e RAGGUARD_API_KEY=ragi_your_key_here -- ragguard mcp
```

**Cursor, Claude Desktop and other MCP clients:**

```json
{
  "mcpServers": {
    "ragguard": {
      "command": "ragguard",
      "args": ["mcp"],
      "env": { "RAGGUARD_API_KEY": "ragi_your_key_here" }
    }
  }
}
```

Tools: `ragguard_status`, `ragguard_run_audit`, `ragguard_list_issues`, `ragguard_get_issue`, `ragguard_check_document`, `ragguard_report`.

### A rule for your assistant

Paste this into `AGENTS.md`, `CLAUDE.md`, `.cursorrules` or `.github/copilot-instructions.md`:

```markdown
## RAG index integrity (RAGGuard)
- After changing ingestion, chunking or embedding code, or after a bulk re-index, run
  `ragguard check --fail-on high` (or the MCP tool `ragguard_run_audit`) and fix every open
  issue it reports before saying the work is done.
- Do not call an ingestion change finished while RAGGuard reports missing, stale, duplicate,
  half-indexed or wrong-tenant chunks.
- When a user reports a wrong or outdated answer, run `ragguard document <document-id>`
  before changing prompts or models: the index is often the cause.
```

## Learn more

- [Guides](https://rag-integrity-platform.vercel.app/guides): eight ways a RAG index drifts, with a check for each
- [Use RAGGuard from your AI assistant](https://rag-integrity-platform.vercel.app/guides/use-ragguard-from-your-ai-assistant)

MIT licensed.
