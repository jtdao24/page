# Semantic Retrieval

Specification for natural-language note search. It covers `page_core.embeddings`
(chunking, embeddings, the vector index), `page_core.retrieval` (the search service and
its runtime), `page_core.api` (the HTTP API) and the desktop search panel.

**Stage status.** In the project plan, semantic indexing and retrieval is **Stage 8**.
This work was written ahead of Stages 4–7 (SQLite persistence and persistent note IDs,
the API, desktop integration, links and graph). It contains the minimum of the API and
desktop pieces that search needs, and is not a Stage 5 implementation. It should be
merged only once those stages are approved, or with an explicitly revised plan. See
[Limitations](#limitations).

## Flow

```
query ─► validate (strip, non-blank, ≤ 2000 chars, 1 ≤ limit ≤ 50)
      ─► embed with the index's Sentence Transformers model (unit L2 vector)
      ─► FAISS inner-product search over chunk vectors (k candidates)
      ─► look up chunk rows in SQLite (path, byte range, heading, text)
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
- Headings start new chunks. Blank lines separate blocks, but blank lines inside fenced
  code don't. A fence closes only on a line of the same character (backtick or tilde),
  at least as long as the opener, followed by nothing but whitespace. Blocks are packed into chunks of up to 1200 characters. A longer block is
  split at line boundaries, and a longer line at whitespace. Leading YAML front matter
  is skipped.
- The embedded text is the note title (the file name without `.md`), then the section
  heading if the chunk doesn't already start with it, then the chunk text. Excerpts
  always come from the raw chunk text.

## Index storage and lifecycle

```
<vault>/.page/index/
├── chunks.faiss     FAISS IndexIDMap2(IndexFlatIP), written atomically
└── chunks.sqlite    meta, notes(path, sha256, size, mtime_ns), chunks(vector_id, path, …)
```

- **Sync** compares each note's size and modification time with the stored values.
  It reads only notes that changed, and re-chunks only notes whose SHA-256 changed.
  Within a changed note, chunks whose text and heading are unchanged keep their row,
  ID and vector, so only new or edited chunks are embedded.
  Deleted or unreadable notes are removed from the index. Embedding happens outside
  the index lock, so searches keep running during a sync.
- **When it runs:** at API startup, every `PAGE_INDEX_SYNC_INTERVAL` seconds (default
  30; `0` disables), on `POST /api/index/sync`, and soon after a search finds stale
  chunks. `SemanticIndex.index_note` and `remove_note` are hooks for a future editor
  that writes notes.
- **Chunk identity:** every chunk has a stable UUID `chunk_id`, which the API returns.
  It is separate from the FAISS label (`vector_id`), which stays internal. A chunk keeps
  its ID when other parts of the note change, when it moves within the note, and across
  restarts. Editing the chunk itself gives it a new ID. Because notes are keyed by path
  until persistent note IDs exist (Stage 4), renaming or moving a note gives all its
  chunks new IDs.
- **Storage safety:** the index never follows symlinks. If `.page`, `.page/index`, or
  `chunks.sqlite` (and its `-journal`, `-wal`, `-shm` files) or `chunks.faiss` is a
  symlink or not the expected kind of entry, opening the index raises
  `IndexStorageError`. Search then reports the error, and nothing is written outside
  the vault. Temporary files are created exclusively and without following links.
- **Consistency:** each update changes SQLite and FAISS under one lock, so searches
  never see the two out of step.
- **Stale results:** before a result is returned, its chunk's bytes are compared with
  the note's current content. Edited or deleted notes are therefore never shown with
  outdated excerpts, even before the next sync.
- **Recovery:** the index is derived data. When it loads, it is reset and rebuilt from
  the Markdown files if any of these hold:
  - the metadata database is corrupt (it can't be opened, or `PRAGMA quick_check`
    fails). The database and vector files are then deleted and recreated;
  - the metadata is missing;
  - the model, dimension, metric, chunk size or storage format changed;
  - the FAISS file can't be read;
  - the FAISS IDs don't match the SQLite chunk IDs (for example, after a crash
    mid-sync).

  A valid index on disk is searchable as soon as the model loads. A brand-new index
  only serves searches after its first full build.

## HTTP API

Start the API with `python -m page_core.api --vault PATH`. It listens on
`127.0.0.1:8765` and allows CORS from the Vite dev server and the Tauri webview.
Handlers are synchronous and run in FastAPI's threadpool, so embedding and FAISS work
never blocks the event loop.

| Method and path | Purpose |
|---|---|
| `POST /api/search/semantic` | `{"query": str, "limit": int = 10}` → `{query, limit, metric: "cosine", model, results[]}` |
| `GET /api/note?path=…` | Read a note by vault-relative path |
| `GET /api/index/status` | `state` (`loading`, `indexing`, `ready`, `error`), counts, model, last sync |
| `POST /api/index/sync` | Sync now and return the report |

Each result has `note_id`, `path`, `title`, `score`, `excerpt`, `matched_chunks` and
`chunk {id, ordinal, start_byte, end_byte, heading}`, where `chunk.id` is the stable
chunk UUID.

| Outcome | Status | `detail.code` |
|---|---|---|
| Matches, or **no matches** (`results: []`) | 200 | |
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
| API URL used by the desktop app | | `VITE_PAGE_API_URL` | `http://127.0.0.1:8765` |

The sync interval must be a finite number of seconds, 0 or more. Negative, NaN and
infinite values are rejected at startup with a configuration error.

Changing the model rebuilds the index on the next start.

Install the pinned dependencies for running the API with real embeddings using
`packages/core/requirements-app.txt` (see the README). `requirements-dev.txt` is enough
for the tests, which use fake embeddings. The model is downloaded from
Hugging Face the first time it is used and cached after that.

## Limitations

- **Stage order:** this work comes ahead of plan Stages 4–7; see the note at the top.
- **Note IDs are per process.** `note_id` comes from the running `FileSystemVault` and
  changes when the API restarts, as specified for Stage 3. The desktop app opens notes
  by `path`. Persistent note IDs are Stage 4. Chunk IDs are stable, but they are tied to
  the note's path until then.
- **Index writes:** the whole FAISS file is rewritten after each sync that changes
  something. Exact (flat) search is linear in the number of chunks. Both are fine for
  personal vaults; an approximate index can replace it later.
- **Change detection:** there is no file watcher. Changes are picked up by the periodic
  sync, a manual sync, or the stale check at search time.
- **Desktop integration:** the desktop app doesn't start the API. Run it separately.
  Starting it from Tauri is the repository's Stage 6.
- The desktop note view is read-only. Editing, the knowledge graph and wiki links are
  later stages.
