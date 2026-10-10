# Local Core API

`page_core.api` exposes the filesystem vault and persistent SQLite
metadata through an authenticated HTTP API on IPv4 loopback. It is a core
development entry point. The desktop app uses it through a trusted Rust HTTP
bridge; see [desktop-integration.md](desktop-integration.md). It offers no search,
AI, graph or packaging features.

## Architecture

```
page_core/api/
  __init__.py   create_app
  app.py        application factory, lifespan, routes, wire conversion
  schemas.py    strict request/response models and wire-string parsers
  service.py    LocalVaultService: session registry and storage orchestration
  security.py   peer/Host/Origin/bearer checks for the whole application
  errors.py     error envelope and exception-to-status translation
  server.py     standalone runner; __main__.py runs it
```

`create_app(*, session_token=None)` returns a FastAPI application. Importing the
package or calling the factory opens no vault or database, starts no thread and
binds no socket; there is no module-level application. Existing imports of
`page_core`, `page_core.domain`, `page_core.vault` and `page_core.metadata` do
not load the API or FastAPI.

Each application has its own credential, session registry and storage worker.
Its lifespan creates one `ThreadPoolExecutor(max_workers=1)` and builds the
`LocalVaultService` on that worker thread. Every storage operation is one job on
that thread: all `PersistentVault` instances and SQLite connections are created,
used, reconciled and closed there, so SQLite's thread checks stay enabled. A
note mutation's lookup, read, revision check and write are a single job, so API
operations never interleave. Health checks, authentication and request
validation run on the event loop and never wait for the worker; a long vault
scan does not block health requests.

A client that disconnects does not cancel submitted storage work, and nothing is
retried. On shutdown, already submitted work finishes first, then every open
vault is closed on the worker, the registry is cleared and the worker exits.

The service uses `PersistentVault.create`, `open`, `reconcile`, `read_note`,
`create_note`, `update_note`, `move_note` and `delete_note`. It reads its
`metadata` repository only to look up and list active records; it never
mutates files through SQL. A read-only `FileSystemVault.open` reads the
manifest first to detect duplicate vault identities.

## Installation and startup

From the repository root, install the pinned environment (FastAPI, Pydantic 2,
minimal Uvicorn, and HTTPX/pytest for tests):

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r packages/core/requirements-dev.txt -e packages/core
```

Start the API:

```sh
.venv/bin/python -m page_core.api              # port 8765
.venv/bin/python -m page_core.api --port 8765
.venv/bin/python -m page_core.api --port 0     # OS-assigned port
```

`--port` accepts integers 0–65535 and is the only option. The server always
binds the literal address `127.0.0.1`; there are no host, reload, worker, proxy
or authentication options. An occupied port is an error (exit status 1), never
a fallback to another port or interface; invalid arguments exit with status 2.
`SO_REUSEADDR` is not set, so a port with lingering connections from a just
stopped server can briefly be reported as occupied.

After binding, the runner writes exactly one JSON line to stdout and nothing
else:

```json
{"host":"127.0.0.1","port":8765,"token":"<session-token>"}
```

`port` is the actual bound port. The token is generated freshly from 32 random
bytes for each run and kept only in memory; it is never written to disk.
Treat the line as a secret for the invoking user or process: do not log it,
paste it into shared places, or store it. The line is not a readiness signal:
poll `GET /api/v1/health` with the token until it returns 200. Diagnostics go
to stderr. Uvicorn runs as one process with reload, proxy headers, WebSockets
and the access log disabled. Ctrl+C or SIGTERM shuts down gracefully, closing
every open vault, and exits with status 0.

`create_app(session_token=...)` accepts a caller-supplied token for trusted
embedding and tests. It must be exactly 43 URL-safe characters; production
callers must generate it with `secrets.token_urlsafe(32)`.

## Access protection

Every request, including health, `/openapi.json`, unknown paths, unsupported
methods and `OPTIONS`, passes these checks before its body is read or any
storage work is scheduled:

| Check | Failure |
| --- | --- |
| The ASGI peer is a loopback IP address | `403 local_access_required` |
| Exactly one `Host` header: `127.0.0.1` or `localhost`, optional port 1–65535 | `400 invalid_host` |
| No `Origin` header at all, including `Origin: null` | `403 origin_not_allowed` |
| Exactly one `Authorization: Bearer <token>` header | `401 unauthorized` with `WWW-Authenticate: Bearer` |

The scheme is case-insensitive and the token is compared case-sensitively in
constant time. Tokens in query strings, cookies, bodies or other headers are
ignored. There is no login, token issuance, JWT or switch to disable
authentication. CORS is not enabled, so browsers cannot use the API. The desktop
Tauri webview invokes fixed commands; Rust sends authenticated requests without
Origin. Credentials never reach React. Standalone API security is unchanged.

All responses carry `Cache-Control: no-store`. Debug pages, trailing-slash
redirects, Swagger UI and ReDoc are disabled. The authenticated
`/openapi.json` describes bearer authentication, the DTOs, `If-Match`
preconditions and error responses. Errors and logs never include tokens,
`Authorization` headers, request bodies, note content, validation input or
exception text. FastAPI request telemetry is disabled.

The token grants the current OS user's access to explicitly opened vaults. It
does not protect against malicious processes already running as that user,
which can read the bootstrap line, the vault files or the database directly.
The filesystem vault's trusted-owner assumption still applies.

## Conventions

- JSON bodies require `Content-Type: application/json` (parameters such as
  `charset` are allowed); other or missing media types return
  `415 unsupported_media_type`. Malformed JSON and invalid values return
  `422 validation_error`.
- Request objects reject unknown fields, `null`, wrong JSON types and coercion.
  Clients never send IDs, timestamps, digests or tombstone state.
- Vault and note IDs are canonical lowercase hyphenated UUIDs, in paths and in
  `known_renames` keys. Other spellings return `422`.
- Vault roots are nonempty absolute native paths without NUL or unencodable
  characters. `~`, environment variables and relative paths are not expanded.
  The vault code resolves roots, including a symlinked root.
- Note paths are canonical relative POSIX strings: no empty, `.` or `..`
  components, no leading or trailing `/`, lowercase `.md`, and the vault's
  managed-path rules (no hidden components, backslashes, colons, NUL, control
  or `< > " | ? *` characters, Windows-reserved names, or names ending in a
  space or dot). Symlinks, non-regular files and case mismatches with existing
  directories are refused by the filesystem layer.
- Note content is any text encodable as strict UTF-8, written byte for byte:
  Unicode, byte order marks, CRLF/CR/LF line endings, empty content and a
  missing final newline are preserved. Markdown is never parsed or rewritten.
- Responses use canonical UUIDs, `/`-separated paths and UTC timestamps with
  six fractional digits, such as `2026-01-01T00:00:00.000000+00:00`. Lists are
  JSON arrays, `[]` when empty. No SQLite paths, SQL, inode/device numbers,
  tombstones or metadata digests are exposed.

## Endpoints

| Method and path | Input | Success |
| --- | --- | --- |
| `GET /api/v1/health` | — | `200 HealthResponse` |
| `POST /api/v1/vaults` | `CreateVaultRequest` | `201 VaultResponse`, `Location` |
| `POST /api/v1/vaults/open` | `OpenVaultRequest` | `200 VaultResponse` |
| `GET /api/v1/vaults` | — | `200 VaultResponse[]` |
| `GET /api/v1/vaults/{vault_id}` | — | `200 VaultResponse` |
| `DELETE /api/v1/vaults/{vault_id}` | — | `204`, empty body |
| `POST /api/v1/vaults/{vault_id}/reconcile` | `ReconcileRequest` (`{}` is valid) | `200 ReconcileResponse` |
| `GET /api/v1/vaults/{vault_id}/notes` | — | `200 NoteSummaryResponse[]` |
| `POST /api/v1/vaults/{vault_id}/notes` | `CreateNoteRequest` | `201 NoteResponse`, `Location`, `ETag` |
| `GET /api/v1/vaults/{vault_id}/notes/{note_id}` | — | `200 NoteResponse`, `ETag` |
| `PUT /api/v1/vaults/{vault_id}/notes/{note_id}` | `UpdateNoteRequest`, `If-Match` | `200 NoteResponse`, `ETag` |
| `POST /api/v1/vaults/{vault_id}/notes/{note_id}/move` | `MoveNoteRequest`, `If-Match` | `200 NoteResponse`, `ETag` |
| `DELETE /api/v1/vaults/{vault_id}/notes/{note_id}` | `If-Match`, no body | `204`, empty body |

`Location` is relative and names the created resource's `GET` URL.

### Request models

| Model | Fields |
| --- | --- |
| `CreateVaultRequest` | `root_path` string, `name` nonblank string (kept verbatim) |
| `OpenVaultRequest` | `root_path` string |
| `CreateNoteRequest` | `relative_path` string, `content` string (default `""`) |
| `UpdateNoteRequest` | `content` string |
| `MoveNoteRequest` | `relative_path` string |
| `ReconcileRequest` | `known_renames` object of note UUID → relative path (default `{}`) |

### Response models

| Model | Fields |
| --- | --- |
| `HealthResponse` | `status` (`"ok"`), `version` (`page_core.__version__`) |
| `VaultResponse` | `id`, `name`, `root_path` (resolved), `needs_reconciliation` |
| `NoteSummaryResponse` | `id`, `vault_id`, `relative_path`, `created_at`, `updated_at`, `revision` |
| `NoteResponse` | summary fields plus `content` |
| `ReconcileResponse` | `added`, `modified`, `renamed`, `missing`, `unchanged` |
| `ErrorResponse` | `error`: `code`, `message`, `details` |

Health reports that the service is alive; it does not check open vaults.

## Vault sessions

The registry starts empty, lives only in memory, and is keyed by each vault's
manifest UUID with its resolved root indexed. A vault ID works only while that
vault is open; unknown or closed IDs return `404 vault_not_found` without
touching the filesystem. `GET /api/v1/vaults` is sorted by root path, then ID.

- **Create** calls `PersistentVault.create`: it makes the folder if needed,
  adopts existing Markdown without rewriting it, writes a new manifest and
  reconciles. An existing manifest is never overwritten: `409 vault_exists`,
  also when that vault is already open.
- **Open** calls `PersistentVault.open`, which reconciles before the session is
  registered. Opening an already open root again, including through a symlink
  or another spelling of the same directory, returns the existing session
  without a new connection and without clearing its recovery state. A
  different root whose manifest has the UUID of an open vault (a copied vault)
  returns `409 vault_identity_conflict` before its metadata is initialized;
  clones are never merged or given new IDs. A missing folder or manifest
  returns `404 vault_not_found`; a corrupt or unsupported manifest returns
  `422 invalid_vault`.
- **Close** (`DELETE /api/v1/vaults/{id}`) only ends the session. It never
  deletes the folder, notes, manifest or database. Reopening restores note IDs
  and creation times. After moving a whole vault folder, close it and open the
  new location; root changes are not discovered automatically.

Platforms without POSIX private-file enforcement fail closed: creation returns
`503 storage_unavailable` before creating a folder or manifest, and opening
returns the same error. Other metadata privacy refusals (for example, a vault
root writable by other users or a hard-linked database) also return
`503 storage_unavailable`.

Creating a vault is not one transaction across the manifest and SQLite. If
metadata initialization fails after the manifest was written, the manifest and
source files are kept, nothing is deleted as rollback, and the session is not
registered. Retrying create then returns `409 vault_exists`: inspect the folder,
fix the reported problem, and use **open**.

## Notes and persistent IDs

Notes are addressed by persistent UUID within the requested vault. The ID is
looked up among that vault's active metadata records; IDs of other vaults,
deleted or missing notes (tombstones) and notes whose file has disappeared
return `404 note_not_found`. After reading, the service checks that the file
at the resolved path still carries the requested ID.

The collection lists active metadata summaries sorted by path, then ID, without
reading note contents, so a note with invalid UTF-8 is listed while reading it
returns `422 unreadable_note`. Collections reflect the last successful
reconciliation plus API operations and refreshed reads. Page does not watch the
filesystem: after files are added, moved or deleted outside Page, call
reconcile.

- `PUT` replaces content only; path and ID are unchanged.
- `move` handles moves and renames, keeps ID, content and creation time, and
  never overwrites an occupied destination (`409 note_exists`). Moving to the
  current path returns the note unchanged.
- `DELETE` permanently deletes the source file. There is no trash or undo;
  folders and the metadata tombstone remain. Creating a note at the same path
  later gives it a new ID.

## Revisions and preconditions

Every note has a `revision`: the lowercase SHA-256 hex digest of the compact
ASCII JSON array

```
[vault UUID, note UUID, relative path, created_at, updated_at, content SHA-256]
```

encoded with `json.dumps(values, ensure_ascii=True, separators=(",", ":"))`.
Full notes hash their returned content's UTF-8 bytes; summaries use the stored
digest, so both report the same revision for the same state. Full-note
responses return it as `ETag: "<revision>"`.

`PUT`, `move` and note `DELETE` require exactly one `If-Match` header with
exactly one strong quoted revision. A missing header returns
`428 precondition_required`; duplicate, weak (`W/`), wildcard, list or
malformed values return `422 validation_error`. In one worker job the service
reads the note, compares revisions and returns `412 revision_conflict` without
writing if they differ. Changed bytes are detected even when size and mtime are
unchanged. A timestamp-only change (for example `touch`) also changes the
revision. After `412`, read the note again and reapply the change.

The filesystem layer then repeats its own snapshot check; a change made by
another program in between returns `409 note_conflict`. Serialization prevents
API requests from interleaving, but the short window between the check and the
write described in [filesystem-vault.md](filesystem-vault.md) still applies to
other programs writing the same files.

## Reconciliation

`POST /api/v1/vaults/{id}/reconcile` calls `PersistentVault.reconcile` and
publishes one complete metadata snapshot in a transaction. Existing paths keep
their IDs; a unique, byte-identical moved file keeps its ID; edited or
ambiguous moves get new IDs unless confirmed:

```json
{"known_renames": {"<note-uuid>": "new/path.md"}}
```

A confirmation needs a source ID whose file is missing and a unique existing
destination; otherwise `422 invalid_reconciliation` is returned and nothing is
published. `PersistentVault.reconcile` reports these rejections as
`page_core.metadata.InvalidRenameError`, a `ValueError` subclass. A failed scan or file read returns an error and leaves the previous
snapshot untouched; unread files are never marked missing.

## Partial success and recovery

A file change and its metadata commit are not one transaction. When the file
operation succeeds but metadata cannot be saved, the API returns:

```json
{"error": {"code": "metadata_sync_failed",
  "message": "The filesystem changed but metadata could not be saved; reconcile the vault.",
  "details": {"filesystem_changed": true, "operation": "move",
              "relative_path": "new/path.md", "note_id": "<note-uuid>",
              "reconciliation_required": true}}}
```

`operation` is `create`, `update`, `move` or `delete`; `relative_path` is the
note's current path; `note_id` is `null` for create, because a failed create has
no committed ID. The file change is kept: Page never undoes it, restores old
content or retries automatically. The session is marked
`needs_reconciliation: true` and all of its note endpoints return
`409 reconciliation_required`. Vault inspection, listing, reconcile and close
still work.

Do not blindly repeat the request: the change has already happened, and a
repeated create or move would fail or act twice. Instead, fix the storage
problem and call reconcile. The flag clears only after a successful
reconciliation; a failed one keeps it. If a failed move could be ambiguous (for
example several notes with identical content), confirm it with the
`note_id` and `relative_path` from the error:
`{"known_renames": {"<note_id>": "<relative_path>"}}`. Closing the session and
opening the vault again also works, because opening reconciles before the
session is registered.

A metadata failure before any file change, such as while refreshing metadata
during a read, returns an ordinary storage error and does not set the flag.
Corrupt or incompatible metadata is reported and never deleted, reset or
recreated; see [sqlite-metadata.md](sqlite-metadata.md) before repairing it
manually.

## Errors

Every error uses one envelope; `details` is `null` unless stated:

```json
{"error": {"code": "stable_machine_code", "message": "safe message", "details": null}}
```

Validation errors list only safe parts:
`{"errors": [{"location": ["body", "relative_path"], "code": "invalid_note_path", "message": "..."}]}`.
Locations never contain submitted values; unknown keys appear as `"*"`.

| Status and code | Meaning |
| --- | --- |
| `400 invalid_host` | Missing, duplicate or non-loopback `Host` |
| `401 unauthorized` | Missing, duplicate, malformed or wrong bearer token |
| `403 local_access_required` | Peer is not a loopback address |
| `403 origin_not_allowed` | Request has an `Origin` header |
| `403 filesystem_forbidden` | The filesystem denied permission |
| `404 route_not_found` | Unknown path (after authentication) |
| `404 vault_not_found` | No open session with this ID, or no vault at the root |
| `404 note_not_found` | No active note with this ID in this vault |
| `405 method_not_allowed` | Unsupported method; `Allow` lists the supported ones |
| `409 vault_exists` | A manifest already exists at the root |
| `409 vault_identity_conflict` | An open vault already has this manifest UUID |
| `409 note_exists` | Create or move destination is occupied |
| `409 note_conflict` | The file changed after the revision check |
| `409 reconciliation_required` | A partial success must be reconciled first |
| `412 revision_conflict` | `If-Match` is not the current revision |
| `415 unsupported_media_type` | Body is not `application/json` |
| `422 validation_error` | Invalid JSON, field, ID, path, `If-Match`, or unmanaged path |
| `422 invalid_vault` | Corrupt or unsupported manifest or vault structure |
| `422 invalid_reconciliation` | Rejected `known_renames` |
| `422 unreadable_note` | Note file is not valid UTF-8 |
| `428 precondition_required` | `If-Match` is missing |
| `500 storage_error` | SQLite failure or undecodable metadata |
| `500 filesystem_error` | Other filesystem failure |
| `500 internal_error` | Unexpected failure |
| `503 storage_busy` | SQLite is busy or locked; retry later |
| `503 storage_unavailable` | Metadata privacy, compatibility or platform refusal |
| `503 metadata_sync_failed` | File changed but metadata was not saved (see above) |

Undecodable stored metadata, such as a malformed stored ID or a stored path the
vault would not manage, returns `500 storage_error` wherever it is met: when
opening a vault (the failed session is not registered and its connection is
closed), when listing, when reading or before changing a note (even if the
corrupt record belongs to another note; no file is changed), and when
reconciling, whether or not `known_renames` was sent. Nothing is published, an
existing `needs_reconciliation` flag stays set, and the database is never reset.
Only confirmations that reconciliation rejects return
`422 invalid_reconciliation`.

## Example

The values below are placeholders. Run each request with the token from the
bootstrap line.

```sh
TOKEN='<session-token>'
API=http://127.0.0.1:8765/api/v1
AUTH="Authorization: Bearer $TOKEN"
JSON='Content-Type: application/json'

curl -s -H "$AUTH" $API/health
curl -s -H "$AUTH" -H "$JSON" -d '{"root_path": "/Users/me/Notes", "name": "Notes"}' $API/vaults
curl -s -H "$AUTH" -H "$JSON" -d '{"root_path": "/Users/me/Work"}' $API/vaults/open
curl -s -H "$AUTH" $API/vaults
V=<vault-id>
curl -s -H "$AUTH" -H "$JSON" -d '{"relative_path": "ideas/first.md", "content": "# First\n"}' $API/vaults/$V/notes
curl -s -H "$AUTH" $API/vaults/$V/notes
N=<note-id>
curl -si -H "$AUTH" $API/vaults/$V/notes/$N            # note the ETag
R=<revision>
curl -s -X PUT -H "$AUTH" -H "$JSON" -H "If-Match: \"$R\"" -d '{"content": "# First\nMore.\n"}' $API/vaults/$V/notes/$N
R=<new-revision>
curl -s -H "$AUTH" -H "$JSON" -H "If-Match: \"$R\"" -d '{"relative_path": "archive/first.md"}' $API/vaults/$V/notes/$N/move
R=<new-revision>
curl -s -X DELETE -H "$AUTH" -H "If-Match: \"$R\"" $API/vaults/$V/notes/$N
curl -s -H "$AUTH" -H "$JSON" -d '{}' $API/vaults/$V/reconcile
curl -s -X DELETE -H "$AUTH" $API/vaults/$V
```

Command-line arguments are visible to other processes of the same user; in
scripts, prefer passing the header through a file or standard input.

## Platform limits

Only macOS has been tested. Private metadata requires POSIX permissions and
`O_NOFOLLOW`, so on Windows creating or opening a vault through the API fails
with `503 storage_unavailable` until verified ACL support exists. The vault's
filesystem races, durability limits and trusted-owner assumption apply
unchanged.

## Deferred

The knowledge graph, semantic search and question answering add the endpoints
described below. MCP and packaging don't change the API, and the desktop app's
connection and process ownership are documented in
[desktop-integration.md](desktop-integration.md). There are no filesystem watchers,
background reconciliation, remote or multi-user access, TLS, uploads,
arbitrary file access, vault deletion, trash, pagination or WebSockets.

## Knowledge graph

The knowledge graph adds authenticated `GET /api/v1/vaults/{vault_id}/graph`, returning
canonical note nodes and directed wiki-link references with unresolved reasons.
See [knowledge-graph.md](knowledge-graph.md) for the wire shape, resolution rules,
refresh behavior and limits. It uses the existing storage worker and session;
no additional server, credential or note-writing endpoint is introduced.


## Semantic indexing and retrieval

Semantic search adds authenticated `POST /api/v1/vaults/{vault_id}/index` and
`POST /api/v1/vaults/{vault_id}/search`. Search reconciles current source and reuses
unchanged embeddings; it returns canonical note and chunk identities, revisions,
source byte/line ranges and exact cosine scores. Model preparation is explicit;
ordinary requests remain offline. See [semantic search](semantic-search.md) for
schemas, model setup, failure handling, incremental behavior and limits.

## Question answering

Question answering adds authenticated `POST /api/v1/vaults/{vault_id}/ask`. It retrieves and
optimizes context like search, then sends only the selected passages and the question
to the configured language model (Gemini, keyed by `GEMINI_API_KEY` at startup) and
returns a cited answer with token usage. This is the only endpoint that contacts a
remote service. See [question answering](question-answering.md) for schemas, errors
and privacy.
