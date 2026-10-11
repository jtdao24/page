# Desktop packaging

Page ships as a macOS app that includes its own Python runtime, Page Core, every Python
dependency and the embedding model. Users install it by dragging it to Applications.
They don't install or configure Python.

## Building

From the repository root, after the [development setup](development.md):

```sh
npm run runtime:prepare   # builds apps/desktop/src-tauri/runtime/ (a few minutes, ~1.1 GB)
npm run tauri:bundle      # builds Page.app and a DMG
```

Output: `apps/desktop/src-tauri/target/release/bundle/macos/Page.app` and
`bundle/dmg/Page_0.1.0_aarch64.dmg` next to it (about 1.07 GB and 366 MB).
Tauri lays out the DMG window through Finder automation. Without that permission,
`CI=true npm run tauri:bundle` skips the layout step.

`npm run tauri:build` still builds without the runtime. A release app built that way
reports `runtime_missing` at startup instead of falling back to a development
environment.

## What's bundled

`apps/desktop/scripts/prepare_runtime.py` assembles `src-tauri/runtime/` (gitignored),
and `src-tauri/tauri.bundle.conf.json` copies it to `Page.app/Contents/Resources/runtime/`:

| Path | Contents |
|---|---|
| `python/` | CPython 3.12.15 from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) release 20261009, a relocatable build. The archive's SHA-256 is pinned in the script. |
| `python/lib/python3.12/site-packages/` | The page-core wheel and its dependencies, at the exact versions in `packages/core/requirements-dev.txt`. Wheels only, nothing compiled. Bytecode is precompiled; tests, C++ headers and pip are removed. |
| `model/` | The pinned MiniLM model (`sentence-transformers/all-MiniLM-L6-v2` at its pinned revision) as a plain folder, with a `page-model.json` marker naming that revision |
| `bin/page-mcp` | Launcher for the [MCP server](mcp.md) using the bundled runtime |

Before finishing, the script runs a smoke test with the bundled interpreter, offline,
exactly as the app runs it: it imports the API and MCP server and embeds a sentence.

**Size:** the runtime is about 1.1 GB, mostly PyTorch (about 580 MB) and
Transformers. Swapping PyTorch for a smaller inference runtime would cut this, but
it would change the embedding stack, which the [evaluation](evaluation.md) measured, so it's left for later.

## How the app runs Core

Debug builds (`npm run tauri:dev`) still run the checkout's `.venv` or `PAGE_PYTHON`.
Release builds run only the bundled interpreter, found next to the executable:

```
Contents/Resources/runtime/python/bin/python3 -I -B -m page_core.api --port 0
```

- `-I` (isolated) ignores `PYTHON*` variables and the user's site-packages, so nothing
  from the user's own Python setup can load into Page.
- `-B` writes no bytecode, so the signed app never modifies itself.
- `PAGE_MODEL_DIR` points to the bundled model, and `HF_HUB_OFFLINE=1`,
  `TRANSFORMERS_OFFLINE=1` and `HF_HUB_DISABLE_TELEMETRY=1` keep model loading offline.

Startup, readiness checks, crash detection, restart and shutdown are unchanged from
[desktop integration](desktop-integration.md). The packaged runtime was also checked
running from a read-only copy.

## Gemini API key

A Finder-launched app doesn't see terminal variables, so the key can now be saved in
the app: the key button in the ask box. Page stores it in the macOS Keychain
(service `com.page.desktop`) and restarts Core to apply it. Unsaved drafts are kept
across the restart. The key goes to Core only through its environment. The webview,
logs and errors never see it.

A saved key takes precedence over `GEMINI_API_KEY`. **Remove Key** deletes it from the
Keychain.

Gemini calls verify TLS with certifi's CA bundle, because python.org and
python-build-standalone builds on macOS don't find the system certificates.

## Permissions

- **Webview:** the Tauri capability grants only Page's own commands, plus the native
  folder picker (`dialog:allow-open`), which returns only the folder the user chooses.
  There's no generic filesystem, shell or HTTP access, and the content security policy allows
  only the app and its IPC.
- **Hardened runtime:** on for the app. The bundled Python and its libraries are
  signed with `src-tauri/runtime-entitlements.plist` when built with a Developer ID. That
  file adds only
  `com.apple.security.cs.allow-unsigned-executable-memory`. ctypes and PyTorch need it.
- **No App Sandbox.** Vaults are arbitrary folders that the user types in. Sandboxing
  needs security-scoped bookmarks and a folder picker first.
- **Network:** only the Ask feature contacts a server (Gemini), and only after the user
  asks a question.

## Signing and notarization

Prepared but not yet validated, because it needs an Apple Developer ID certificate:

```sh
# 1. Sign every Mach-O file in the runtime with the hardened runtime and a timestamp.
.venv/bin/python apps/desktop/scripts/prepare_runtime.py --sign "Developer ID Application: NAME (TEAMID)"
# 2. Build. Tauri signs the app and, with these set, notarizes and staples it.
APPLE_SIGNING_IDENTITY="Developer ID Application: NAME (TEAMID)" \
APPLE_ID=you@example.com APPLE_PASSWORD=app-specific-password APPLE_TEAM_ID=TEAMID \
npm run tauri:bundle
```

For a local build without a certificate, sign ad hoc:

```sh
.venv/bin/python apps/desktop/scripts/prepare_runtime.py --sign -
APPLE_SIGNING_IDENTITY=- npm run tauri:bundle
```

Ad hoc signatures have no Team ID. The hardened runtime's library validation would
reject the bundled Python libraries, so the script signs ad hoc runtimes without it.
A Developer ID signs the app and every library with one Team ID, which library
validation accepts. Unsigned and ad hoc builds run on the Mac that built them. On
another Mac, Gatekeeper blocks them until the user allows them under System Settings →
Privacy & Security.

## Installing and updating

- **Install:** open the DMG and drag Page to Applications.
- **Update:** replace the app with a newer one. User data is kept, because none of it
  is inside the app:
  - notes and each vault's `.page/` metadata stay in the vault folders;
  - preferences stay in `~/Library/Application Support/com.page.desktop/`;
  - the Gemini key stays in the Keychain.

  Embeddings are rebuilt automatically only if the model changes.
- **Uninstall:** delete the app. Vault folders are untouched. The preferences folder
  and the Keychain item can be removed by hand.
- **No automatic updates yet.** Tauri's updater needs signed update artifacts and a
  release server, which depend on the signing setup above.

## Validation

On macOS 26.6 on Apple silicon, October 10, 2026, with ad hoc signing:

- `codesign --verify --deep --strict` passes, both before and after the app has run,
  so Core writes nothing inside the bundle.
- Opening `Page.app` starts the bundled interpreter with the arguments and environment
  above. Core listens only on 127.0.0.1. Quitting stops the app and Core.
- The bundled Core was driven through the API with an empty environment, as an app
  launched from Finder would get: health, vault creation, notes, and semantic search
  using the bundled model all worked. Ask without a key returned `llm_not_configured`.
  The first search in a new Core process took 10–30 s (loading PyTorch and the model);
  later searches reuse the loaded model.
- The bundled `page-mcp` launcher served `get_context` to an MCP client.
- The runtime also ran from a read-only copy, and its Gemini client completed a TLS
  handshake with Google's API host.

Not validated: Developer ID signing, notarization, Gatekeeper on a second Mac,
Intel Macs and Windows.

## Platforms

Built and checked on macOS 26 on Apple silicon (`aarch64-apple-darwin`), with a
minimum of macOS 14, which PyTorch, NumPy, SciPy and FAISS require. The script also
pins the Intel macOS and Windows runtimes, but neither has been built or tested.
Windows isn't usable yet anyway: Page Core's metadata storage fails closed there.
