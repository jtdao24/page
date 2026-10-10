# Page

Page is a local-first, AI-native knowledge workspace for macOS and Windows. It pairs
Obsidian-style Markdown notes with a context engine whose goal is to give language
models only the context a task needs, so that fewer input tokens are used without losing
answer accuracy. Whether it achieves that will be measured, not assumed.

## Architecture

Several interfaces share one engine:

- **Page Desktop** (`apps/desktop`): Tauri 2 shell with a React + TypeScript frontend.
- **Page Core** (`packages/core`): Python package for knowledge processing, retrieval
  and context selection. It runs on its own, without the desktop app.
- **Page Integrations** (`integrations/`): planned adapters, such as MCP, that expose
  Page Core to external tools.

Notes stay as plain Markdown files that the user owns. The engine will not depend on any
particular LLM provider.

## Technology stack

| Area     | Tools                                                |
| -------- | ---------------------------------------------------- |
| Core     | Python 3.12, hatchling, pytest, FastAPI, Sentence Transformers, FAISS, SQLite |
| Desktop  | Tauri 2 (Rust), React 19, TypeScript 6 (strict), Vite 8, Tailwind CSS 4 |
| Tooling  | npm workspaces, ESLint, Vitest, rustfmt              |

## Repository structure

```
apps/desktop/         Desktop app (React frontend in src/, Tauri shell in src-tauri/)
packages/core/        page-core Python package (src layout, import name page_core)
integrations/mcp/     Reserved for the MCP integration
training/             Reserved for model training code
benchmarks/           Reserved for evaluation and benchmarks
docs/                 Project documentation (domain-models.md, filesystem-vault.md,
                      semantic-retrieval.md)
```

## Prerequisites

Both platforms:

- Python 3.12
- Node.js 24 LTS and npm 11
- Rust stable (via [rustup](https://rustup.rs)), including the `rustfmt` component

macOS:

- Xcode Command Line Tools: `xcode-select --install`

Windows:

- Microsoft C++ Build Tools ("Desktop development with C++" workload)
- Microsoft Edge WebView2 Runtime (preinstalled on Windows 10 1803+ and Windows 11)

For the full list, see [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/).

## Installation

From the repository root:

```sh
# JavaScript dependencies (all workspaces, from package-lock.json)
npm ci

# Python environment with pinned dev dependencies and an editable page-core
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r packages/core/requirements-dev.txt -e packages/core
```

`packages/core/requirements-dev.txt` pins the exact versions of the `dev` dependency
group and the runtime dependencies declared in `packages/core/pyproject.toml`. To run
the API with real embeddings, also install the extras (this pulls in PyTorch):

```sh
python -m pip install -e "packages/core[api,embeddings]"
```

## Python tests

```sh
python -m pytest packages/core
```

## Frontend checks

```sh
npm run typecheck   # TypeScript (strict)
npm run lint        # ESLint
npm test            # Vitest
npm run build       # Type check + Vite production build
```

Rust formatting and checks, run from `apps/desktop`:

```sh
npm run rust:fmt:check
npm run rust:check
```

## Running the Page Core API

Semantic search needs the API running beside the desktop app:

```sh
python -m page_core.api --vault ~/Documents/Page --init "My Notes"
```

`--init` creates the vault manifest if the folder isn't a Page vault yet; existing
Markdown files are adopted untouched. The first start downloads the embedding model and
indexes every note, and later starts reuse the index in `<vault>/.page/index/`. See
[docs/semantic-retrieval.md](docs/semantic-retrieval.md) for the endpoints and settings.

## Running the desktop app

```sh
npm run tauri:dev     # Development window with hot reload
npm run tauri:build   # Release build and platform bundles
```

To run only the frontend in a browser, use `npm run dev` (http://localhost:1420).

App icons in `apps/desktop/src-tauri/icons/` are generated from `apps/desktop/app-icon.png`
with `npm run tauri -w @page/desktop -- icon`. Only the desktop icons listed in
`tauri.conf.json` are kept.

## Status

**Stage 3 of 14: filesystem vault.** Completed so far:

1. Repository foundation: layout, tooling, a desktop shell that displays "Page", and an
   installable `page-core` package.
2. Core domain models: immutable, validated `Vault`, `Note`, `Link`, `Chunk` and
   `ContextResult` types in `page_core.domain`, specified in
   [docs/domain-models.md](docs/domain-models.md).
3. Filesystem vault: `page_core.vault` creates and opens vaults and safely lists,
   reads, creates, updates, moves and deletes Markdown notes, specified in
   [docs/filesystem-vault.md](docs/filesystem-vault.md). Note IDs are kept in memory
   only until Stage 4.

Semantic retrieval (built from the "Phase 2, Stage 5" brief, whose numbering differs from
this list): `page_core.embeddings` chunks notes and keeps a persistent FAISS + SQLite
index, `page_core.retrieval` answers natural-language queries with note-level results,
`page_core.api` serves them over HTTP, and the desktop app has a search panel and note
view. It is specified in [docs/semantic-retrieval.md](docs/semantic-retrieval.md).
Persistent note IDs (Stage 4) and launching the API from Tauri (Stage 6) are still to do.
