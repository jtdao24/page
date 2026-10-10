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
| Core     | Python 3.12, hatchling, FastAPI, Pydantic 2, Uvicorn, pytest, HTTPX |
| Desktop  | Tauri 2 (Rust), React 19, TypeScript 6 (strict), Vite 8, Tailwind CSS 4 |
| Tooling  | npm workspaces, ESLint, Vitest, rustfmt              |

## Repository structure

```
apps/desktop/         Desktop app (React frontend in src/, Tauri shell in src-tauri/)
packages/core/        page-core Python package (src layout, import name page_core)
integrations/mcp/     Reserved for the MCP integration
training/             Reserved for model training code
benchmarks/           Reserved for evaluation and benchmarks
docs/                 Project documentation (domain models, filesystem vault, SQLite metadata, local API)
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

`packages/core/requirements-dev.txt` pins exact versions of the runtime dependencies
(FastAPI, Pydantic, Uvicorn), the `dev` dependency group (pytest, HTTPX) declared in
`packages/core/pyproject.toml`, and all of their transitive packages.

## Python tests

```sh
python -m pytest packages/core
```

This includes the local API tests and a real loopback server smoke test.

## Running the core API

Page Core runs on its own as an authenticated local HTTP API, bound only to
`127.0.0.1`:

```sh
python -m page_core.api              # port 8765
python -m page_core.api --port 0     # OS-assigned port
```

It prints one JSON line with the host, actual port and a fresh session token, which
must be sent as `Authorization: Bearer <token>`. Keep that line private. See
[docs/local-api.md](docs/local-api.md) for endpoints, readiness checks and security
limits.

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

**Stage 5 local API, with desktop and semantic indexing work.** Completed so far:

1. Repository foundation: layout, tooling, a desktop shell that displays "Page", and an
   installable `page-core` package.
2. Core domain models: immutable, validated `Vault`, `Note`, `Link`, `Chunk` and
   `ContextResult` types in `page_core.domain`, specified in
   [docs/domain-models.md](docs/domain-models.md).
3. Filesystem vault: `page_core.vault` creates and opens vaults and safely lists,
   reads, creates, updates, moves and deletes Markdown notes, specified in
   [docs/filesystem-vault.md](docs/filesystem-vault.md). Note IDs are kept in memory
   only when using the standalone Stage 3 interface.
4. SQLite metadata: `page_core.metadata` adds versioned migrations, persistent
   note IDs and creation timestamps, transactional CRUD, and reconciliation
   through an opt-in filesystem adapter. Notes remain the source of truth;
   this adapter does not parse Markdown or perform vector indexing.
   See [docs/sqlite-metadata.md](docs/sqlite-metadata.md) for usage and limitations.
5. Local Core API: `page_core.api` serves an authenticated FastAPI interface on
   IPv4 loopback for opening, creating, reconciling and closing vault sessions and
   for listing, reading, creating, updating, moving and deleting notes by persistent
   UUID, with revision checks against stale writes. See
   [docs/local-api.md](docs/local-api.md).
6. Optional ingestion and semantic indexing: secure Markdown scanning,
   heading-aware tokenizer-budgeted chunks,
   MiniLM embeddings, persistent SQLite metadata/vector caches, recoverable FAISS
   indexing, background progress, and an authenticated local desktop bridge.
   See [docs/ingestion.md](docs/ingestion.md) for setup, API and recovery behavior.

Private Stage 4 metadata permissions are currently enforced on POSIX and tested on
macOS. Windows metadata support fails closed pending verified ACL enforcement, so
the Stage 5 API cannot open vaults there yet; the existing Stage 2/3 interfaces retain
their behavior. The optional ingestion
service maintains its own index cache; it is started separately from the metadata
adapter.

The desktop connects to the separately launched ingestion service; it does not yet
use the Stage 5 vault and note API. Backend knowledge-graph
relationships, neural reranking and packaged core-process lifecycle are not implemented yet.

The main dashboard displays indexed notes as an interactive node graph, with
text filters, collection colors, pan/zoom, and recent entries. Graph connections
show shared collections. Workspace controls sit at the top of the collapsible
vault sidebar, below a separate Page brand row. Each entry opens in its own closable app tab with full
Markdown, contents, source view, and file provenance. Before connecting a
vault, it shows a labeled sample library. See
[docs/graph-workspace.md](docs/graph-workspace.md) for graph/tab behavior and limits.
The sidebar shows files from one selected folder, with a folder switcher at the bottom.
The question composer saves an unsent
draft locally; Gemini integration is planned and the send control is disabled.
Vault connection and indexing controls are available in Vault settings.

The Page landing page is available at `http://localhost:1420/landing.html`, with
bold typography, the app's paper-and-green palette, a mission statement, and an
interactive sample graph. `npm run landing:export` creates a standalone static
website with a ZIP download of the existing Apple Silicon desktop build;
`npm run landing:preview` serves it at `http://localhost:4173`.
The development app still requires a separately installed Python core for real
vaults. See [docs/landing-page.md](docs/landing-page.md) for build and hosting details.

Account interfaces are bundled in the Tauri 2 frontend: `/login`, `/signup`, and
`/forgot-password`, plus Profile & account settings in the sidebar toolbar.
Online authentication is not configured; all account requests remain unavailable,
and local vault access never requires sign-in. See
[docs/authentication-frontend.md](docs/authentication-frontend.md) for the provider
interface, validation, navigation, and testing details.
