# Use RAGGuard from your AI assistant

> Let Claude Code, Cursor, Copilot or any MCP-capable assistant check your RAG index for you: a rule to paste into your project, an MCP server, and a command your assistant can run.

If an AI assistant writes or changes your ingestion code, it should also check that the index is still right afterwards. RAGGuard gives it three ways to do that.

## 1. Add a rule to your project

Paste this into your assistant's rules file: `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md` or similar.

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

## 2. Install the command and get an API key

```bash
pip install "ragguard-cli[mcp] @ git+https://github.com/kishore600/rag-integrity-platform#subdirectory=clients/python"
```

Create an API key in RAGGuard on the **Integrations** page, then set it where your assistant runs:

```bash
export RAGGUARD_API_KEY=ragi_your_key_here
```

The key can run audits and read results. It cannot read your connection settings or create other keys.

## 3. Connect the MCP server

**Claude Code:**

```bash
claude mcp add ragguard -e RAGGUARD_API_KEY=ragi_your_key_here -- ragguard mcp
```

**Cursor** (`.cursor/mcp.json`), **Claude Desktop** and other MCP clients:

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

Your assistant then has these tools:

| Tool | What it does |
|---|---|
| `ragguard_status` | The health score, document and issue counts, and the latest audit |
| `ragguard_run_audit` | Runs an audit, waits for it to finish and returns the summary |
| `ragguard_list_issues` | The open issues, most severe first, optionally by severity |
| `ragguard_get_issue` | One issue with its evidence and the recommended fix |
| `ragguard_check_document` | Everything RAGGuard knows about one document |
| `ragguard_report` | The full audit report as Markdown |

Then ask: "Is my RAG index in sync?" or "Why does the bot still quote the old refund policy?"

## 4. Or use the command directly

```bash
ragguard check --fail-on high   # run an audit; exit code 1 if open issues are high or critical
ragguard status                 # the latest results, without running an audit
ragguard issues --severity high # open issues
ragguard document refund-policy.pdf
```

`ragguard check` works in CI too: add it after your ingestion job, and the job fails when the index drifts.

Not using RAGGuard yet? [Create a workspace](https://rag-integrity-platform.vercel.app/signup), connect your bucket and your Qdrant or pgvector index, and create the API key. It is free during the beta.
