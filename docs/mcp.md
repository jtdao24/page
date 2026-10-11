# MCP integration

Page's knowledge search and context optimization are available to AI agents through
the [Model Context Protocol](https://modelcontextprotocol.io). An MCP client, such as
Claude Code or Claude Desktop, starts Page's server and calls its tools to find,
compress and cite your notes.

## What it can and can't do

The server gives an agent a better way to fetch context: a few relevant, budgeted
passages with sources, instead of whole files. It can't make the agent use those
tools, and it can't shrink anything else the agent sends to its model, such as the
conversation, other tools' output, or files it reads directly. Token savings apply only
to the context fetched through Page.

## Tools

All tools are read-only and work on one vault, chosen when the server starts.

| Tool | Input | Returns |
|---|---|---|
| `get_context` | `question`, `budget` (50–20,000 tokens, default 1,500), `candidates` (1–50, default 10) | Numbered, source-attributed context that fits the budget; each source's note, path, line range, relevance and whether it was trimmed to an excerpt; token usage |
| `search_notes` | `query`, `limit` (1–50, default 10) | The most similar passages, with path, lines and cosine score |
| `read_note` | `path` | A note's full Markdown, ID and revision |
| `related_notes` | `path` | Wiki links from the note and backlinks to it, with line numbers; unresolved links say why (`missing`, `ambiguous`, `invalid`) |

`get_context` uses the same pipeline as the desktop ask box: semantic search, then
context optimization ranked by cosine similarity (see [evaluation](evaluation.md) for
why the learned reranker isn't used). Token counts use Page's `utf8-bytes/3` estimate,
not the client model's tokenizer.

Each call reads the saved files, so notes edited in Page or another editor are
picked up. Unsaved drafts in the app are not.

## Setup

Prerequisites: the development environment from [Developing Page](development.md),
the prepared embedding model (`.venv/bin/python -m page_core.semantic prepare-model`),
and an existing Page vault (create one in the app).

Use absolute paths below. Replace `/path/to/page` with this checkout and
`/path/to/vault` with your vault's folder.

**Claude Code:**

```sh
claude mcp add page -- /path/to/page/.venv/bin/python -m page_core.mcp_server --vault /path/to/vault
```

**Claude Desktop and other clients** that use an `mcpServers` JSON configuration
(for Claude Desktop, `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "page": {
      "command": "/path/to/page/.venv/bin/python",
      "args": ["-m", "page_core.mcp_server", "--vault", "/path/to/vault"]
    }
  }
}
```

**With the installed app**, no checkout is needed. Use its bundled launcher as the
command:

```sh
claude mcp add page -- /Applications/Page.app/Contents/Resources/runtime/bin/page-mcp --vault /path/to/vault
```

To check the server by hand, run the same command. It waits for an MCP client on
stdin; a folder that isn't a Page vault exits with an error.

## Errors

Failures return MCP tool errors (`isError`) with a code and a fixed message, for
example `note_not_found: No note at plans/trip.md.` or
`model_unavailable: Prepare the local embedding model before searching.` The codes
match the [local API](local-api.md). Invalid arguments are rejected by the tool's input
schema. Messages never include note text, absolute paths or tracebacks.

## Privacy

The server runs locally over stdio, opens no network port and calls no language model.
Embedding runs on your machine. But whatever a tool returns goes to the agent's model,
which may be a cloud service: passages from `get_context` and `search_notes`, and whole
notes from `read_note`. Only connect vaults you're willing to share with that model.

## Limits

- One vault per server. Add the server twice under different names for two vaults.
- Read-only: agents can't create or edit notes through Page.
- The server and the desktop app can use the same vault at once. Both update the vault's
  metadata and embedding cache, and SQLite serializes their writes; a busy database
  returns `storage_busy`.
- The first `get_context` or `search_notes` call loads the embedding model and indexes
  changed notes, so it can take tens of seconds (about 20 s for a 17-note vault on an
  Apple silicon Mac). Later calls reuse the model and unchanged embeddings.
- stdio only; no HTTP transport or authentication.
- Tested with the MCP Python SDK's own client in-process and over stdio, on macOS.
