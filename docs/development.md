# Developing Page

Setup, architecture and validation instructions for contributors. The desktop
workflow is currently verified on macOS. Windows vault access is not yet supported.

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
| Core     | Python 3.12, FastAPI, Sentence Transformers, FAISS, PyTorch, pytest |
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
(FastAPI, Pydantic, Uvicorn, Sentence Transformers, FAISS), the `dev` dependency group (pytest, HTTPX) declared in
`packages/core/pyproject.toml`, and all of their transitive packages.

## Local semantic search model

Prepare the fixed pretrained model once before using desktop semantic search:

```sh
.venv/bin/python -m page_core.semantic prepare-model
```

This downloads model files only. Ordinary indexing and search use the local cache
and send no note or query content to a service. See [semantic search](semantic-search.md)
for source attribution, incremental indexing, API contracts and limitations.

## Neural reranker

Stage 9's learned reranker reorders semantic search candidates. With the model
prepared, retrain it and re-measure it on held-out queries:

```sh
.venv/bin/python -m page_core.ranking train      # writes training/reranker/model.json
.venv/bin/python -m page_core.ranking evaluate   # writes benchmarks/reranker.json
```

See [neural ranking](neural-ranking.md) for features, the checkpoint format, the
dataset and current results.

## Context optimization

Stage 10's `page_core.context.optimize_context` packs ranked passages into
source-attributed context that fits a token budget, dropping repeats and trimming
oversized passages to exact excerpts. See [context optimization](context-optimization.md).

## Benchmark

Stage 11 compares full context, embedding top-k and the Page optimizer on held-out
questions:

```sh
.venv/bin/python -m page_core.evaluation run   # writes benchmarks/results/stage11.*
```

See [evaluation](evaluation.md) for metrics, results and limits.

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

The Rust tests include authenticated HTTP transport, process lifecycle, preferences,
and a real Python backend integration test on macOS:

```sh
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml
```

## Running the desktop app

```sh
npm run tauri:dev     # Development window with hot reload
```

The macOS development app starts this checkout's `.venv/bin/python` directly. The
environment must already contain the editable `page-core` package and pinned
dependencies. Set `PAGE_PYTHON` to one absolute interpreter path to override it;
relative paths, shell arguments and PATH fallback are refused. No dependency
installation occurs at application startup.

Stage 6 dependencies and matching lockfiles are operator-prepared; see
[docs/desktop-integration.md](docs/desktop-integration.md) for their exact versions.
`npm run tauri:build` remains a build command, but bundled Python, installers and
distribution validation are deferred to Stage 14.

To run only the frontend in a browser, use `npm run dev` (http://localhost:1420).
It displays a desktop-runtime-unavailable state: vault access requires Tauri.

App icons in `apps/desktop/src-tauri/icons/` are generated from `apps/desktop/app-icon.png`
with `npm run tauri -w @page/desktop -- icon`. Only the desktop icons listed in
`tauri.conf.json` are kept.
