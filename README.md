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

**Stage 5 of 14: Local Core API.** Completed so far:

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
   no parsing, API, UI integration, embeddings, or vector indexing are included.
   See [docs/sqlite-metadata.md](docs/sqlite-metadata.md) for usage and limitations.
5. Local Core API: `page_core.api` serves an authenticated FastAPI interface on
   IPv4 loopback for opening, creating, reconciling and closing vault sessions and
   for listing, reading, creating, updating, moving and deleting notes by persistent
   UUID, with revision checks against stale writes. See
   [docs/local-api.md](docs/local-api.md).

Private metadata permissions are currently enforced on POSIX and tested on
macOS. Windows metadata support fails closed pending verified ACL enforcement, so
the API cannot open vaults there yet; the existing Stage 2/3 interfaces retain their
behavior.

The desktop app is not connected to Page Core yet, and no retrieval, search or AI
features are implemented.
