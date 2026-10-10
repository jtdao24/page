# Semantic Retrieval

Specification for natural-language note search. It covers `page_core.embeddings`
(chunking, embeddings, the vector index), `page_core.retrieval` (the search service and
its runtime), `page_core.api` (the HTTP API) and the desktop search panel.

This was built from the "Phase 2, Stage 5: Semantic Retrieval" brief. That brief
assumes an earlier stage for chunking, embeddings and FAISS that this repository did not
have yet, so this work adds the minimum of it that search needs. It does not add
persistent note IDs, the repository's own Stage 4. See [Limitations](#limitations).

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
  code don't. Blocks are packed into chunks of up to 1200 characters. A longer block is
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
  It reads only notes that changed, and re-embeds only notes whose SHA-256 changed.
  Deleted or unreadable notes are removed from the index. Embedding happens outside
  the index lock, so searches keep running during a sync.
- **When it runs:** at API startup, every `PAGE_INDEX_SYNC_INTERVAL` seconds (default
  30; `0` disables), on `POST /api/index/sync`, and soon after a search finds stale
  chunks. `SemanticIndex.index_note` and `remove_note` are hooks for a future editor
  that writes notes.
- **Consistency:** each update changes SQLite and FAISS under one lock, so searches
  never see the two out of step.
- **Stale results:** before a result is returned, its chunk's bytes are compared with
  the note's current content. Edited or deleted notes are therefore never shown with
  outdated excerpts, even before the next sync.
- **Recovery:** the index is derived data. When it loads, it is reset and rebuilt from
  the Markdown files if any of these hold:
  - the metadata is missing;
  - the model, dimension, metric, chunk size or format changed;
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
`chunk {id, ordinal, start_byte, end_byte, heading}`.

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

Changing the model rebuilds the index on the next start. The model is downloaded from
Hugging Face the first time it is used and cached after that.

## Limitations

- **Note IDs are per process.** `note_id` comes from the running `FileSystemVault` and
  changes when the API restarts, as specified for Stage 3. The desktop app opens notes
  by `path`. Persistent note IDs are the repository's Stage 4.
- **Index writes:** the whole FAISS file is rewritten after each sync that changes
  something. Exact (flat) search is linear in the number of chunks. Both are fine for
  personal vaults; an approximate index can replace it later.
- **Change detection:** there is no file watcher. Changes are picked up by the periodic
  sync, a manual sync, or the stale check at search time.
- **Desktop integration:** the desktop app doesn't start the API. Run it separately.
  Starting it from Tauri is the repository's Stage 6.
- The desktop note view is read-only. Editing, the knowledge graph and wiki links are
  later stages.
