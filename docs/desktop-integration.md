# Desktop integration

Page Desktop is a macOS development application using Tauri 2, React, TypeScript
and CodeMirror 6. Markdown files remain authoritative. Acceptance is
complete on macOS: native functional checks passed and the user accepted the
visual layout on October 10, 2026. Backend integration is verified on macOS 26.6.2
(25G83). Windows is unverified and private metadata access still fails closed
there with `storage_unavailable`. Release builds run a bundled Python runtime; see
[packaging](packaging.md).

The workspace uses an Obsidian-inspired dark palette and a sidebar with labeled
actions (New note, Search, Graph, Ask, with their shortcuts) above the Files tree. The
sidebar collapses to an icon rail; collapsing preserves the current editor, selection,
undo history and draft. A rounded ask box floats over the note (Cmd/Ctrl+K). The theme
uses soft blues taken from the app icon, and motion is disabled for users who prefer
reduced motion.

With no vault open, the home screen offers three choices that use the native folder
picker (the Tauri dialog plugin, granted only `dialog:allow-open`): start with a
sample vault of linked starter notes, create a vault in a chosen folder, or open
one. Recent vaults are listed below. Paths are never typed: ⌘O and Open vault go
straight to the picker, and the sidebar's vault name opens the same three choices. A five-step intro appears
on first launch (remembered in the webview's local storage) and can be replayed from
the home screen. With a vault open and no note selected, quick actions offer a new
note, saving a web page, the graph and Ask.

## Boundaries and commands

React → typed `PageClient` → Tauri commands → Rust `CoreApiClient` → authenticated
IPv4 loopback API → `PersistentVault`. Rust and React never read or write note
files, manifests or databases directly. Python Core remains independent of Tauri.

| Module | Responsibility |
| --- | --- |
| `src/core/types.ts`, `client.ts` | Wire DTOs, safe discriminated errors, explicit snake_case IPC mapping |
| `src/workspace/controller.ts`, `useWorkspace.ts` | Async ownership, drafts, dirty guards, restoration and recovery |
| `src/workspace/text.ts`, `tree.ts` | Line endings and lexical folders derived from note summaries |
| `src/components/MarkdownEditor.tsx` | CodeMirror lifecycle, serialization, highlighting and undo |
| `src/components/Workspace.tsx` | Workspace composition, shortcuts, status and confirmation dialogs |
| `src-tauri/src/backend.rs` | Owned subprocess, bootstrap, readiness, generations, monitoring and shutdown |
| `src-tauri/src/api.rs` | Fixed endpoint construction, HTTP policy, DTO/ETag validation and errors |
| `src-tauri/src/commands.rs` | Main-window/webview caller checks and blocking-task dispatch |
| `src-tauri/src/preferences.rs` | Validated, private, atomic workspace settings |

Exposed commands: `backend_start`, `backend_status`, `backend_restart`;
`vault_create`, `vault_open`, `vault_list`, `vault_get`, `vault_close`,
`vault_reconcile`; `note_list`, `note_read`, `note_create`, `note_update`,
`note_move`, `note_delete`; `preferences_read`, `preferences_write`, `desktop_quit`;
`graph_read`, `semantic_index`, `semantic_search`, `ask_question`; `source_list`,
`source_read`, `web_page_save`; `gemini_key_status`,
`gemini_key_save`, `gemini_key_clear` (the key goes to the system credential store, never
back to the webview).
There is no generic URL, HTTP, filesystem, SQL or shell command. Wire fields
match [local-api.md](local-api.md); timestamps stay strings, IDs come from Core,
and revisions are opaque accepted snapshots. Full notes require a matching strong
ETag. Mutations send the last accepted revision in a quoted `If-Match` header.

## Development startup and ownership

Run `npm run tauri:dev` after operator dependency preparation. Rust resolves the
checkout from its compile-time manifest directory and launches `.venv/bin/python`
with the argument vector `-m page_core.api --port 0`, never through a shell.
`PAGE_PYTHON` optionally supplies one nonempty absolute interpreter path, used
verbatim without argument splitting, environment expansion or PATH search.
Missing/misconfigured interpreters produce a safe actionable error. Launching
the app installs or downloads nothing. Browser-only `npm run dev` disables vault
actions and explains that the desktop runtime is required.

One application owns at most one child. Concurrent starts share startup. Rust
privately reads a complete bootstrap line of at most 4096 bytes, rejecting unknown
fields, anything except literal `127.0.0.1`, invalid ports and tokens that are not
43 URL-safe ASCII characters. Authenticated health is polled every 100 ms, with
a one-second request timeout and overall 20-second startup deadline. Bootstrap
alone is insufficient for readiness. Subsequent stdout and stderr are discarded
through bounded buffers; rejected data and credentials are never logged or emitted.

Rust detects unexpected child exit within one second, invalidates the generation
and reports failure. Restart is explicit and uses a fresh child and credential;
it preserves in-memory drafts and reopens the active root without replaying writes.
Requests and process waits run on worker/blocking threads. HTTP explicitly disables
proxies, redirects and retries, with a two-second connect and 30-second total
timeout. No Origin header is sent and authorization is marked sensitive.

## Workspace actions and fidelity

Creating and opening vaults use the native folder picker; a new vault is named after
its folder.
Create adopts existing managed Markdown files without rewriting them. Open failure
never creates a vault. Resolved roots/IDs returned by Core are remembered; open
sessions and recent selections are displayed separately. Close Vault closes the
session without deleting files.

The sidebar is built only from note summaries, with nested navigable folders and
deterministic lexical ordering. New Note uses a user-entered canonical relative
path ending in lowercase `.md`. Rename / Move uses the complete destination path;
occupied destinations remain errors. Delete requires a separate confirmation naming
the path and stating that it is permanent, with no trash or undo.

Save is explicit (Cmd/Ctrl+S). Cmd/Ctrl+N starts New Note, Cmd/Ctrl+O opens vault
forms; CodeMirror handles undo/redo. Clean saves are no-ops. Save acknowledgments
update only the accepted snapshot; typing during a save remains dirty. A failed
list refresh after an acknowledged mutation is reported separately.

Changing notes/vaults, creating another note, moving, deleting, closing and native
quit use Save / Discard / Cancel when dirty. Failed/uncertain saves or additional
typing block the transition. Discard is an in-memory action. Escape cancels forms
and dialogs; it never silently discards a draft. Dialogs contain keyboard focus
and restore it on closure. Native main-window close and Quit route to the same guard.

UTF-8 content, Unicode, BOMs, empty documents and missing final newlines are
preserved. Uniform LF, CRLF and CR are serialized using their original separator.
Mixed endings remain read-only until an explicit conversion-to-LF confirmation;
conversion makes the draft dirty and does not save. CodeMirror views are destroyed
on document replacement; undo never crosses note identities. Save retains the
existing view, selection and undo history. Markdown, names and errors are text;
there is no HTML preview or executable link handling.

## Conflicts, uncertain outcomes and recovery

Revision/file conflicts keep the draft and its old revision. A separately fetched
disk snapshot is shown as text. Keep Draft closes comparison; Reload from Disk
requires discard confirmation; Use My Draft requires overwrite confirmation and
one save using the newly fetched revision. Further disk edits can conflict again.
Missing notes retain orphan drafts for copying or explicitly creating a new note
at a chosen path. Unreadable UTF-8 notes remain listed; other notes can still open.

Timeout, disconnect, child death or invalid mutation response may mean storage
changed. Such operations become unknown outcomes and block further mutation.
Verify Outcome reconciles and reads fresh state; it never repeats the mutation.
Failed verification keeps the block. Restart does not resend interrupted writes.

`metadata_sync_failed` explicitly means filesystem change with failed metadata
synchronization. Mutations pause until successful reconciliation and fresh state.
Reconcile normally sends an empty `known_renames`; a separate confirmed failed-move
action sends only the reported ID/destination. Recovery never deletes or resets
a database. Refresh from Disk reconciles external changes and shows counts; it
updates clean documents, preserves dirty/orphan drafts and opens conflicts when
dirty notes differ from disk. There are no watchers or autosave.

## Remembered workspace

Rust stores `workspace.json` under Tauri's app configuration directory
(`~/Library/Application Support/com.page.desktop` on macOS). Format version 1:

```json
{"version":1,"recent_vaults":[],"active_vault_id":null}
```

Each recent entry contains `vault_id`, resolved `root_path`, and nullable
`last_note_id`. Up to ten entries are ordered most recent first and deduplicated
by root and ID. Preferences contain no drafts, content, revisions, server endpoint,
credential or executable setting. Writes are ordered and use atomic same-directory
replacement with owner-only directory/file permissions on macOS. Symlinks and
non-regular preference files are refused.

Startup reads preferences, starts Core, opens only the remembered active root and
restores the last note if present. Missing roots produce a visible error; missing
notes clear selection. A different manifest ID requires user acceptance. Malformed,
unsupported or unreadable settings produce a warning and remain preserved until
Reset Remembered Workspace is explicitly confirmed. Settings write errors remain
separate from successful note saves.

## Security and shutdown limits

Custom application-command permissions grant only the fixed commands to `main`;
handlers also check window/webview identity. Capabilities have no remote grants.
CSP allows bundled assets and IPC, plus localhost HMR WebSockets during development.
It prohibits inline scripts, eval, frames, objects and frontend Python connections.
Inline styles are allowed for CodeMirror. Navigation is confined to the application
origin (and configured Vite origin in debug); new windows are denied. Standalone
API Origin rejection and bearer checks are unchanged.

After approved quit, pending mutations settle, then Rust sends SIGTERM to its own
unreaped child on macOS. It waits up to ten seconds, then kills/reaps and joins pipe
readers if necessary. Forced OS termination, power loss and renderer crashes cannot
guarantee draft preservation or graceful shutdown. Drafts have no crash recovery.
The existing trusted-owner filesystem assumptions remain; this is not protection
against other malicious processes running as the same user.

## Operator-prepared dependencies

Manifests, installed/cache contents and lockfiles were prepared by the operator
before implementation. This change installs no dependencies, changes no dependency
declarations and adds no transitive lockfile entries.

| Direct dependency | Exact version / features | Purpose |
| --- | --- | --- |
| `@tauri-apps/api` | 2.11.1 | IPC and events |
| `@codemirror/state` | 6.7.6 | Editor state and separators |
| `@codemirror/view` | 6.43.14 | Editor DOM and selection |
| `@codemirror/commands` | 6.11.1 | Editing and undo/redo |
| `@codemirror/language` | 6.13.1 | Highlighting |
| `@codemirror/lang-markdown` | 6.5.2 | Markdown editing |
| `jsdom` (dev) | 26.1.0 | DOM interaction tests |
| `reqwest` | =0.13.5; no defaults, `blocking`, `json` | Loopback HTTP |
| `serde` | =1.0.229; `derive` | Typed serialization |
| `serde_json` | =1.0.151 | JSON bootstrap/settings |
| `libc` (macOS only) | =0.2.190 | Owned-child SIGTERM |

The CodeMirror pins resolve one shared state/view implementation. No new Python
dependencies are needed; use Python 3.12 with the existing pinned requirements
and editable `page-core`. Do not substitute versions or install during implementation.

## Requirement-to-test mapping

| Requirement | Automated evidence |
| --- | --- |
| 1–2: boundaries and typed commands | TypeScript checks; `core/client.test.ts`; Rust caller/DTO/endpoint tests |
| 3–4: launch, bootstrap, readiness and failure | Rust `backend::tests` with fake children, short deadlines, concurrent start, restart, crash and reap |
| 5: fixed HTTP bridge | Rust `api::tests`, `tests/proxy.rs`, every route/header/body, ETags, errors, redirects, unknown mutation/no retry |
| 6: security boundary | Rust caller/capability/CSP/navigation tests; browser-unavailable React test |
| 7–8: vault/note workflow | Workspace/controller tests plus real Python bridge CRUD/reopen test |
| 9–10: editor fidelity and explicit saves | Actual CodeMirror DOM tests, serialized PageClient arguments, mixed conversion, save selection/undo, duplicate shortcuts and dirty guards |
| 11–12: conflicts and recovery | Controller and UI conflict/unknown/orphan/metadata recovery tests; real-backend stale revision/external reconcile |
| 13: async isolation | Deferred-promise tests for old reads/lists, crash/restart, typing during save/refresh and failed verification |
| 14: persistence | Rust private atomic settings, symlink/type/version/limit tests; controller restoration/identity/reset tests |
| 15: shutdown/restart | Rust graceful/forced/reaped tests; controller pending-save quit; native Cmd+Q/window-close cancellation, normal shutdown and relaunch verified |
| 16: usability and shortcuts | DOM focus/dirty/dialog/shortcut tests; native shortcuts, Tab containment/restoration and 800×600 size verified; user visual acceptance recorded October 10, 2026 |

Tests use temporary data and mocks only at external IPC boundaries. The real
integration test launches the production manager/client and checks source bytes,
stable note IDs/timestamps, stale revisions, restart/reopen and closed loopback ports.
DOM measurement shims supply only missing jsdom Range geometry; they do not replace
the editor or controller.

## Validation results

Verified on macOS: Python Core tests (807 passed), frontend tests (53 passed),
TypeScript checks, ESLint, production build, Cargo format check and Cargo check.
Rust tests also passed (45 unit tests and two integration tests). Socket-binding
tests required execution outside the filesystem sandbox. The production build
reports a nonfatal warning for its 785 kB editor-containing JavaScript chunk.
Native functional smoke checks passed. The user accepted the visual layout on
October 10, 2026, completing acceptance on macOS.

## Native smoke evidence and visual acceptance

Verified on macOS 26.6.2 (25G83) on October 10, 2026, after the user enabled
Accessibility. AppleScript drove the real Tauri window, CodeMirror editor and
production backend using a disposable `/private/tmp/page-native-smoke-*` vault:

- Created a vault and adopted existing nested notes. Unicode/LF, CRLF and CR
  edits saved exact expected source bytes using Cmd+S and the Save button.
- Cmd+N created an empty nested note. Move succeeded; an occupied destination
  retained both source and destination. Delete cancellation retained the note;
  confirmed permanent deletion removed it.
- An external edit caused a stale-save conflict without overwriting disk bytes.
  Overwrite cancellation retained disk content; reload required a second
  confirmation. A missing note retained its draft and saved as a separate note.
- Dirty navigation Cancel and Save worked; Discard retained the previously
  saved bytes. Cmd+Q and the native close button opened the dirty guard, and
  Cancel retained the editor draft and running application.
- Three Tab presses cycled from the note-path input through Create/Cancel back
  to the input. Cancel restored editor focus, verified by subsequent native
  typing and saving without refocusing the editor.
- Close Vault retained source files. Reopening the vault listed its notes.
  Explicit Core restart restored selection and retained all note bytes/mtimes.
- Normal Cmd+Q exited the app and its owned Python child; the child's loopback
  listening port was closed. Relaunch restored the active vault and last note,
  retaining every test note's bytes and modification time.
- A deliberately nonexistent `PAGE_PYTHON` produced the actionable
  `interpreter_not_found` screen; Retry remained safe. Relaunching with the
  normal configuration restored the remembered workspace.
- Accessibility reported the initial 1024×720 window size and accepted resizing
  to 800×600. The workflow and Tab checks ran at the minimum size as well.

The user accepted the visual layout on October 10, 2026 ("looks good to me"),
following the request to inspect readability, reachable controls and clipping
at the required sizes, including a dialog and a long note path. This is human
acceptance evidence. Automated window capture was unavailable:
`CGPreflightScreenCaptureAccess()` returned false. No screenshot or automated
visual inspection is claimed.

The following procedure is retained for future validation runs.

Run the checks in [development.md](development.md), then launch
`npm run tauri:dev`. Use a disposable vault outside real notes:

1. Check startup, create/open and nested lexical navigation. Edit Unicode with
   LF/CRLF/CR documents and save using both the button and Cmd+S.
2. Create, rename/move, cancel delete, then confirm permanent delete. Ensure
   occupied destinations remain errors and Close Vault leaves files intact.
3. Edit a saved file externally; attempt a stale save and compare/reload/reapply
   through explicit confirmations. Refresh from Disk; inspect counts and orphan
   draft preservation for missing notes.
4. Navigate with a dirty draft; try each Save/Discard/Cancel choice. Test Cmd+N,
   Cmd+O, Cmd+Q and native window close. Canceling quit must retain draft and child.
5. Quit normally and verify the owned backend exits. Relaunch and check active
   root/last-note restoration without writes. Test startup failure and explicit restart.
6. Check keyboard focus and long paths/errors at 1024×720 and 800×600.

Record actual native smoke evidence for future acceptance runs. Automated
build/tests do not prove an installable distribution or Windows support.
