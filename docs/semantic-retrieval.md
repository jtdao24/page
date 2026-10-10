# Semantic Retrieval

Specification for natural-language note search (Stage 5). It covers
`page_core.embeddings` (chunking, embeddings, the vector index),
`page_core.retrieval` (the search service and its runtime), `page_core.api` (the HTTP
API) and the desktop search panel.

**Stage status.** This is Stage 5, Semantic Retrieval. Its prerequisite, Stage 4
(Markdown ingestion and semantic indexing), is being built separately and is not on
`main` yet. So this work includes the minimum indexing that search needs: chunking,
embeddings, the FAISS index, and persistent note and chunk identities. When Stage 4
lands, the two implementations should be reconciled into one index. See
[Limitations](#limitations).

## Flow

```
query ─► validate (strip, non-blank, ≤ 2000 chars, 1 ≤ limit ≤ 50)
      ─► embed with the index's Sentence Transformers model (unit L2 vector)
      ─► FAISS inner-product search over chunk vectors (k candidates)
      ─► look up chunk rows in SQLite (note, path, byte range, heading, text)
      ─► drop chunks whose bytes no longer match the note on disk
      ─► group by note, keeping each note's best chunk
      ─► rank notes, cut to limit
```

## Ranking and scores

- Vectors are L2-normalized, and the FAISS index is `IndexFlatIP`, so a score is the
  **cosine similarity** between the query and a chunk. Scores range over [-1, 1], and
  higher means more similar.
- A note's score is the score of its **best-matching chunk**. Notes are ordered by
  descending score, then by path. Each note appears at most once, and `matched_chunks`
  counts how many of the retrieved candidate chunks came from it.
- Scores only rank results from the same model. They are **not probabilities or
  confidence values**, and their typical range depends on the model. The desktop app
  shows them as plain numbers (for example, `0.56`).
- The search fetches `max(20, 5 × limit)` candidate chunks. If those yield fewer than
  `limit` distinct notes, it doubles `k` until it has enough notes, runs out of chunks,
  or reaches 1000 candidates.

## Chunking

- Chunks are exact substrings of the note, located by UTF-8 byte range `[start, end)`,
  the same convention as `page_core.domain.Chunk`.
- Headings start new chunks. ATX headings follow CommonMark:
  - A closing run of `#` is removed only when whitespace precedes it, so `# C#` is the
    heading "C#", `# value###` is "value###", and `# value ###` is "value".
  - An empty heading (`#`) starts a section without a label.
- Blank lines separate blocks, but blank lines inside fenced code don't. A fence closes
  only on a line of the same character (backtick or tilde), at least as long as the
  opener, followed by nothing but whitespace.
- Blocks are packed into chunks of up to 1200 characters. A longer block is split at
  line boundaries, and a longer line at whitespace. Leading YAML front matter is
  skipped.
- The embedded text is the note title (the file name without `.md`), then the section
  heading if the chunk doesn't already start with it, then the chunk text. Excerpts
  always come from the raw chunk text.

## Identity

| ID | Scope | Kept when |
|---|---|---|
| `note_id` (UUID) | One per indexed note, stored in the index | Restarts; edits; renames, moves and swaps that keep the note's exact content |
| `chunk_id` (UUID) | One per chunk | Restarts; edits elsewhere in the note; the chunk moving within the note; the note being renamed |
| `vector_id` | FAISS label | Internal only; never returned |

- **Renames and moves.** Identity follows exact content. When a note's stored content
  is no longer at its path (the file is gone or now holds other content), and another
  path now holds exactly that content, that path takes over the note's ID and chunk
  IDs. If several match, the same file (device and inode) wins, then the first path in
  sorted order. Because the title is part of the embedding text, a renamed note's
  chunks are re-embedded under their existing IDs.
- **Edits.** A chunk whose text and heading are unchanged keeps its ID and its vector,
  and only new or edited chunks are embedded. Editing a chunk gives it a new ID.
- **Limits.** A note that is both renamed and edited between two syncs is indexed as a
  new note. A copy of a note gets its own ID, and the original keeps its ID.
- `GET /api/note` and search results report the same `note_id` for a note. A note that
  hasn't been indexed yet has `id: null`.

## Index storage and lifecycle

```
<vault>/.page/index/
├── chunks.faiss     FAISS IndexIDMap2(IndexFlatIP), written atomically
└── chunks.sqlite    meta; notes(note_id, path, sha256, size, mtime_ns, device, inode);
                     chunks(vector_id, chunk_id, note_id, ordinal, byte range, heading, text)
```

- **Sync** compares each note's size and modification time with the stored values. It
  reads only notes that changed, and re-chunks only notes whose SHA-256 changed.
  Deleted or unreadable notes are removed from the index. Embedding happens outside the
  index lock, so searches keep running during a sync. The report counts notes added,
  updated, moved, removed, unchanged and failed.
- **When it runs:** at API startup, every `PAGE_INDEX_SYNC_INTERVAL` seconds (default
  30; `0` means only at startup and on request), on `POST /api/index/sync`, and soon
  after a search finds stale chunks. `SemanticIndex.index_note` and `remove_note` are
  hooks for a future editor that writes notes.
- **Consistency:** each update changes SQLite and FAISS under one lock, so searches
  never see the two out of step.
- **Stale results:** before a result is returned, its chunk's bytes are compared with
  the note's current content. Edited or deleted notes are therefore never shown with
  outdated excerpts, even before the next sync.

### Storage safety

The index writes only to files it owns inside the vault. Opening it raises
`IndexStorageError`, writes nothing, and makes search report the error if any of
these hold:

- `.page` or `.page/index` is a symlink, a Windows junction or other reparse point, or
  not a directory.
- `chunks.sqlite`, its `-journal`, `-wal` or `-shm` file, or `chunks.faiss` is any of:
  - a symlink or reparse point;
  - not a regular file;
  - a file with **more than one hard link**, because another name for the same file
    could be outside the vault.

To narrow the window between checking and opening, the database file is checked before
SQLite opens it and again afterwards. If it is no longer the same file (device and
inode), the connection is closed and the error raised. The vector file is opened with
`O_NOFOLLOW` where the platform has it, and checked again through the open handle. New
vector files are written to an exclusively created temporary file and swapped in with
`os.replace`, which replaces the directory entry rather than writing through it.

These checks assume, like the vault itself, that no hostile process is changing the
vault folder while Page is using it. They are not a defence against an attacker racing
the checks with the same user's permissions.

### Recovery

The index is derived data. When it loads, it is reset and rebuilt from the Markdown
files if any of these hold:

- the metadata database is corrupt (it can't be opened, or `PRAGMA quick_check` fails).
  The database and vector files are then deleted and recreated;
- the metadata is missing;
- the model, dimension, metric, chunk size or storage format changed;
- the FAISS file can't be read;
- the FAISS file isn't an `IndexIDMap2` over an exact inner-product (`IndexFlatIP`)
  index of the right dimension. An L2 index, for example, would rank results backwards;
- its ID map doesn't match its vector count or contains duplicates;
- its IDs don't match the SQLite chunk IDs (for example, after a crash mid-sync).

A valid index on disk is searchable as soon as the model loads. A brand-new index only
serves searches after its first full build.

## HTTP API

Start the API with `python -m page_core.api --vault PATH`. It listens on
`127.0.0.1:8765`. Handlers are synchronous and run in FastAPI's threadpool, so
embedding and FAISS work never blocks the event loop.

### Access control

- **Token.** Every request must send `Authorization: Bearer <token>`. Otherwise the
  response is `401` with `detail.code` `unauthorized` and `WWW-Authenticate: Bearer`.
  - The token is 32 random bytes (43 characters), generated for each launch and
    printed to the console for the user to paste into the desktop app.
  - A process that starts the API can supply its own token through `PAGE_API_TOKEN`,
    which must be at least 32 printable ASCII characters. That is how a desktop
    launcher can pass it on later.
  - The token is never accepted as a command-line argument, since other users can see
    those in the process list. It is never written to the vault, which may be synced.
  - Tokens are compared in constant time.
- **Host.** Only `Host: 127.0.0.1` and `Host: localhost` are accepted. Other hosts get a
  `400`, which blocks DNS-rebinding attacks from web pages.
- **CORS** allows only the Vite dev server and Tauri webview origins. Browser
  preflights are answered without a token, but they reach no endpoint. CORS limits
  which web pages can read responses; it is not the access control itself.
- Interactive docs and the OpenAPI schema are disabled.
- The desktop app keeps the token in `sessionStorage` for the window's session. It
  returns to the connect screen whenever the API answers `401`, for example after the
  API restarts with a new token.

### Endpoints

| Method and path | Purpose |
|---|---|
| `GET /api/health` | `{"status": "ok"}` |
| `POST /api/search/semantic` | `{"query": str, "limit": int = 10}` → `{query, limit, metric: "cosine", model, results[]}` |
| `GET /api/note?path=…` | Read a note by vault-relative path; `id` is its persistent note ID |
| `GET /api/index/status` | `state` (`loading`, `indexing`, `ready`, `error`), counts, model, last sync |
| `POST /api/index/sync` | Sync now and return the report |

Each result has `note_id`, `path`, `title`, `score`, `excerpt`, `matched_chunks` and
`chunk {id, ordinal, start_byte, end_byte, heading}`, where `chunk.id` is the stable
chunk UUID.

| Outcome | Status | `detail.code` |
|---|---|---|
| Matches, or **no matches** (`results: []`) | 200 | |
| Missing or wrong token | 401 | `unauthorized` |
| Blank query, bad limit, unknown field | 422 | |
| Model or index still loading, first build in progress, or startup failed | 503 | `index_unavailable` |
| Query vector doesn't fit the index | 503 | `index_incompatible` |
| Embedding the query failed | 500 | `embedding_failed` |

## Configuration

| Setting | Flag | Environment variable | Default |
|---|---|---|---|
| Vault folder | `--vault` | `PAGE_VAULT_PATH` | (required) |
| Create a vault if there is none | `--init NAME` | | |
| Model | `--model` | `PAGE_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions) |
| Sync interval (seconds) | `--sync-interval` | `PAGE_INDEX_SYNC_INTERVAL` | 30 |
| Port | `--port` | `PAGE_API_PORT` | 8765 |
| API token | | `PAGE_API_TOKEN` | generated per launch |
| API URL used by the desktop app | | `VITE_PAGE_API_URL` | `http://127.0.0.1:8765` |

- The sync interval must be a finite number of seconds, 0 or more. Negative, NaN and
  infinite values are rejected at startup with a configuration error.
- Changing the model rebuilds the index on the next start. The model is downloaded from
  Hugging Face the first time it is used and cached after that.
- To run the API with real embeddings, install the pinned dependencies from
  `packages/core/requirements-app.txt` (see the README). The tests use fake embeddings,
  so `requirements-dev.txt` is enough for them.

## Limitations

- **Stage 4 overlap:** this includes the minimum Stage 4 indexing that search needs.
  When the separate Stage 4 work is merged, the two should become one index.
- **Vault note IDs:** `FileSystemVault` still assigns its own IDs in memory only (Stage
  3). The API reports the index's persistent `note_id` instead, and opens notes by path.
- **Index writes:** the whole FAISS file is rewritten after each sync that changes
  something. Exact (flat) search is linear in the number of chunks. Both are fine for
  personal vaults; an approximate index can replace it later.
- **Change detection:** there is no file watcher. Changes are picked up by the periodic
  sync, a manual sync, or the stale check at search time.
- **Desktop integration:** the desktop app doesn't start the API. Run it separately and
  paste the token it prints.
- The desktop note view is read-only. Editing, the knowledge graph and wiki links are
  later work.
