# Stage 4: Markdown ingestion

This checkout contains Stage 2 domain models and the Stage 3 filesystem vault.
There is no existing knowledge graph, SQLite store or HTTP API to extend. Stage 4
adds `page_core.ingestion`; it uses the existing `Vault`, `Note` identities, `Chunk`
domain contract and managed-path rules. Stage 2 domain objects remain free of I/O.
The neural reranker is deferred.

## Install and run

Use Python 3.12 and the existing development environment:

```sh
python -m pip install -e 'packages/core[ingestion]'
python -m page_core.ingestion.server /absolute/path/to/existing/vault
```

The directory must already be a Page vault (`FileSystemVault.create` creates the
`.page/vault.json` manifest in an existing Markdown directory without replacing notes).
The bridge binds only `127.0.0.1:8765` and prints a random session token. Enter it
in the desktop's Vault indexing panel and select Connect, then Index changes.
The React frontend polls status asynchronously once per second. Index changes and
Rebuild index queue a background worker and return immediately. The model is loaded
on demand and reused; initial loading may include a download. Failures appear in the UI.

The first integration uses an explicitly launched core service for both React and
Tauri. Automatic child-process startup and distribution of a Python runtime/model
with the Tauri release are future packaging work. Python ingestion currently
requires POSIX directory descriptors and advisory locks (macOS/Linux); it fails
explicitly on Windows. The existing vault's Windows behavior is unchanged.

## Storage and publication

Markdown remains authoritative. Generated files live in `.page/ingestion/`:

| File | Purpose |
| --- | --- |
| `chunks.sqlite3` | Notes/UUIDs, SHA-256 digests, filesystem identities, chunk provenance, float32 vector cache, generation/configuration/checksum |
| `vectors.faiss` | Replaceable `IndexIDMap2(IndexFlatIP)` snapshot; cosine scores from normalized vectors |
| `writer.lock` | Serializes writers across processes |
| `publication.lock` | Coordinates metadata/index publication and recovery across processes |

SQLite assigns positive integer `vector_id` values to chunks. FAISS stores those
IDs explicitly rather than depending on row offsets or UUID truncation. Search
joins the returned IDs back to SQLite metadata. Rebuilt FAISS snapshots use all
live vectors; no fragile incremental deletion is used. SQLite commits atomically
before a temporary artifact is flushed and renamed into place. A crash between
these operations leaves a durable vector cache and triggers recovery on reopen
or search. Connections are local to each operation/worker and always closed.

A SHA-256 checksum is checked before deserializing FAISS. Missing, corrupted,
stale-generation and ID-mismatched artifacts are rebuilt from cached vectors
without reembedding. SQLite is the durable cache: a damaged SQLite database raises
an error rather than guessing identities. Back up `.page/ingestion` if retaining
IDs matters; removing the whole cache permits fresh ingestion but loses persisted
identities. This does not delete Markdown. Rebuild index reparses all notes and
reconstructs FAISS while reusing compatible cached embeddings.

Scanning/chunking/embedding happen before publication, so failures leave the prior
indexed generation usable. Search can read that generation while embeddings are
being prepared; the short publication phase serializes readers. Status uses its
own lock and remains available throughout indexing. An unchanged scan does not
rewrite SQLite or FAISS. Deleted-note vectors are removed when unreferenced.

## Incremental scanning and identity

The scanner uses no-follow directory/file descriptors, skips hidden entries,
symlinks, special files and nonportable note paths, and limits notes to 16 MiB.
Every note is hashed on each scan; this detects edits with unchanged size/mtime.
An unchanged digest/configuration skips chunking and embedding. Read failures,
invalid UTF-8 and concurrent file mutation abort a scan rather than causing false
deletions. Scanning is explicitly triggered; no filesystem watcher is included.
Index cache directories/files are also checked for symlinks and special files.
As with the filesystem vault, arbitrary hostile replacement of the entire vault
or metadata directory by another local process is outside the cache trust model.

Same-path edits retain IDs. A missing note and a new path are matched first by
device/inode and then by a unique content digest. Ambiguous copies receive new
IDs. A move combined with rewriting the inode and contents cannot be inferred
reliably and may receive a new ID. After publication the in-memory vault registry
is synchronized, including forgetting removed paths. Reopening `IngestionIndex`
restores persisted IDs into its `FileSystemVault`; standalone vault instances
retain their original in-memory behavior. Restore before retaining snapshots.

Chunk embedding reuse is independent of chunk position: exact text plus pinned
model revision identifies a cached vector. Changing a heading/section can change
chunk boundaries; any unchanged resulting text still reuses its vector.

## Chunking and embeddings

ATX and setext headings delimit sections; heading-like text in backtick/tilde
fences does not. Prefer paragraph, newline and space boundaries, splitting oversized
blocks further using tokenizer counts. The implementation is a focused Markdown
section chunker, not a full CommonMark AST. Very large fenced blocks may be split.

Each chunk contains an exact contiguous source span and records note UUID, chunk
UUID/ordinal, UTF-8 byte interval, line interval, heading ancestry and token count.
Whitespace-only spans are omitted. Heading ancestry is metadata, not text inserted
outside the token budget. The default is 254 tokenizer tokens, reserving two special
tokens within MiniLM's 256-token limit. Budget changes invalidate chunking state.

`sentence-transformers/all-MiniLM-L6-v2` is pinned to revision
`c9745ed1d9f207416be6d2e6f8de32d1f16199bf`. One reusable worker is shared per core
process and lazily loads one model. Embeddings are generated in batches of 32,
validated and normalized as
384-dimensional float32 vectors. CPU thread counts are restricted to one for
PyTorch and FAISS to prevent macOS native-thread oversubscription and reduce desktop
contention. Model encode calls are serialized; status never waits for model execution.
The model worker uses private JSON pipes and keeps PyTorch separate from FAISS.
This avoids their bundled OpenMP runtime conflict on macOS without a duplicate
library workaround. Tokenization uses the same pinned model tokenizer in the
worker. Worker startup, model loading and download are all deferred. The worker
is shared across MiniLM instances, is stopped on normal process exit, and is
restarted on the next request if it exits unexpectedly.

See the [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2),
[SentenceTransformer encode API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
and [FAISS IDMap2 API](https://faiss.ai/cpp_api/struct/structfaiss_1_1IndexIDMap2Template.html).

## Local API

Every endpoint requires `Authorization: Bearer <session-token>`. Only the desktop
development and Tauri origins are allowed by CORS; other supplied origins are
rejected. The session token is never persisted in browser storage. The service
selects its vault at startup; clients cannot supply arbitrary filesystem paths.

| Method/path | Behavior |
| --- | --- |
| `GET /api/index/status` | Vault name; state, phase, scanned/total notes, changed/skipped/deleted notes, embedded/reused vectors, error |
| `POST /api/index` | Queue incremental indexing; 202 or 409 when busy |
| `POST /api/index/rebuild` | Queue a full chunk/FAISS rebuild using reusable cached embeddings |
| `POST /api/dev/search` | Only enabled with `--development-search`; JSON `{"query":"...", "limit":10}` |

Development search returns cosine scores and chunk provenance, including the source
digest. Limit is 1–100 and the body is bounded to 8 KiB. It is disabled by default.
Search results describe the last committed scan; rescan after external edits/deletes.
Errors in background work are returned in status. No neural reranking is performed.

## Validation and benchmark

```sh
python -m pytest packages/core
PAGE_TEST_MODEL=1 python -m pytest packages/core/tests/test_ingestion_model.py
npm run typecheck
npm run lint
npm test
npm run build
PYTHONPATH=packages/core/src python benchmarks/ingestion.py --notes 100 --queries 30 --output benchmarks/macos-ingestion.json
```

Tests use deterministic embeddings to test storage/mapping/recovery without network
or model downloads; the benchmark exercises the actual pinned MiniLM model and
FAISS. It separates model loading, initial indexing, an unchanged scan, a one-note
edit and end-to-end warm queries. The corpus is synthetic and the resulting timings
are a local engineering baseline, not a retrieval-quality evaluation.

Validation on macOS arm64 with Python 3.12.15: 216 pytest tests passed, including
the opt-in real model test; TypeScript, ESLint, Vitest (1 test), and Vite production
build passed. Initial runs exposed native PyTorch/FAISS OpenMP aborts; isolating
the model worker resolved them. A sandboxed API test initially could not bind a
loopback socket; it passed with socket access. Node 23 emitted engine warnings
(the repository recommends Node 24). Rust/Tauri native checks could not run because
Cargo was unavailable; no Rust code was changed.

The recorded 100-note/300-chunk, 30-query benchmark in
[`benchmarks/macos-ingestion.json`](../benchmarks/macos-ingestion.json) measured
7.29 s initial indexing, 7.1 ms unchanged scanning, 29 ms single-note editing, and
5.58 ms median / 6.12 ms p95 warm end-to-end queries. Model loading is reported
separately, and package versions are recorded in the artifact.
