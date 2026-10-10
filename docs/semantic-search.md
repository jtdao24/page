# Stage 8: semantic indexing and retrieval

Page searches saved Markdown by meaning using a fixed pretrained model and an
exact local similarity baseline. Markdown remains the source of truth. There is
no custom model training, reranking, token-budget optimization, answer generation,
or claim that retrieval reduces LLM token usage while preserving answer accuracy.

The Stage 8 scope comes from `tools/stage_runner/context/stage-plans.md`; a separate
Stage 8 specification is not present in this checkout.

## Setup and local execution

Install the pinned Python requirements using the contributor setup, then prepare
the model once:

```sh
.venv/bin/python -m page_core.semantic prepare-model
```

This explicit setup downloads pretrained model files from Hugging Face into the
normal Hugging Face cache. It sends no note content. The fixed model is
`sentence-transformers/all-MiniLM-L6-v2`, revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, with 384-dimensional embeddings.
It is English-oriented, licensed Apache 2.0, and runs on CPU with remote model
code disabled and safetensors weights. It is a baseline choice, not a claim of
best relevance for all vaults or languages.

Normal indexing and searching use `local_files_only=True`. A missing model gives
`503 model_unavailable` with a safe setup message; regular vault operations work
without preparing it. Empty vaults return empty results without loading a model.
No cloud account or API key is required. Queries, passages, and vectors stay on
the local machine during indexing and search.

Sentence Transformers and FAISS are runtime dependencies, including their CPU
PyTorch/NumPy dependencies. The development requirements pin the tested macOS
Python 3.12 environment. No JavaScript or Rust dependency was added.

## Chunks and source attribution

`split_note` produces the existing immutable domain `Chunk` values from canonical
`PersistentVault` Notes. It separates paragraphs and ATX headings, then splits
long spans at the model tokenizer's character boundaries with a 220-token budget.
It re-tokenizes slices to account for WordPiece continuations. Special tokens
are excluded from the chunk count; model input limits are checked before encoding
so text is not silently truncated.

Chunks retain exact original Markdown, including Unicode, BOM, CRLF/CR/LF and
Markdown syntax. Byte ranges are half-open UTF-8 intervals, and each result's text
is precisely that interval from the saved source. Blank/tokenless spans are not
indexed. Frontmatter, code and comments are not deliberately stripped; this is
paragraph-based source chunking, not a full CommonMark renderer. There is no overlap
or automatic heading prefix that would change source attribution.

A chunk UUID is UUID5 under its canonical note UUID, using the chunker version,
budget, exact text digest, and occurrence count for identical chunks. Moving a
note or inserting a preceding paragraph preserves unaffected chunk identities.
Editing a chunk changes its identity. Identical duplicate chunks are distinguished
by occurrence; their identities cannot express historical identity across insertion
of an identical preceding duplicate. A result also carries the canonical note ID,
current path, note revision, ordinal, source line range, and cosine score.

Source line numbers are one-based, with CRLF counted as one separator. Navigation
opens the note through the existing dirty draft guard; it does not yet scroll the
editor to a passage. The revision describes the source snapshot that was read,
not a guarantee against another program editing the file afterward.

## Persistence and incremental updates

SQLite migration 3 adds `semantic_vectors` to the existing private metadata
repository. Each row stores chunk UUID, canonical note UUID (foreign key), a
model/chunker/dimension fingerprint, and normalized little-endian float32 vector
bytes. It stores no Markdown text. The existing owner-only permissions, file
verification, transactions and migration history apply. Deleting metadata cascades
to its vectors; missing files are removed from the next derived snapshot.

Each index or search request reconciles the vault and reads all active notes using
persisted canonical identities. It regenerates chunks from current source, reuses
vectors for unchanged chunk IDs and the same fingerprint, and embeds only new or
changed chunks. Moves retain embeddings while source paths and revisions update.
External edits and additions are discovered on the next request. Cache updates
commit atomically after all source reads and encodes succeed; failed reads or
inference leave the previous vector snapshot intact and return an error rather
than stale search hits.

Vectors must have the expected dimension, finite values and unit norm. Invalid
cache values produce `503 index_corrupt`; an explicit rebuild regenerates them.
A model/chunker fingerprint change invalidates reuse. Rebuilding derived vectors
does not rebuild metadata or change historical note identities. Never delete the
metadata database to repair only the semantic index.

## Retrieval baseline

The embedding model runs in evaluation mode on CPU with one PyTorch inference
thread. Exact FAISS `IndexFlatIP` searches normalized vectors, equivalent to
cosine similarity. Scores are sorted descending with chunk UUID as the deterministic
tie-breaker, including ties at the top-k boundary. No approximate index, stochastic
ranking, graph expansion, reranker, or relevance threshold is used. Nonempty vaults
return the best available passages even when all similarities are low; a score is
not a calibrated relevance probability.

FAISS runs in a fresh local Python process with one OpenMP thread. The tested
macOS PyTorch and FAISS wheels bundle conflicting OpenMP runtimes and abort if
both runtimes initialize in the same process. Isolation avoids the unsafe
`KMP_DUPLICATE_LIB_OK` workaround. Only vectors are sent over stdin; stdout returns
scores and positions. No note text, query text, HTTP credential, or FAISS binary
index is passed to or loaded by this process. Failure/timeout returns a safe
embedding error.

This favors correctness and a reproducible baseline over large-vault performance:
requests scan/read all notes, rebuild the in-memory exact FAISS index from persisted
vectors, and retrieve all scores before stable top-k selection. Encoding is
incremental, but scanning, cache snapshot replacement, and exact search are not.
The process startup and serialization also add latency. Storage/encoding runs on
the existing single storage worker, so CRUD may queue during a large indexing run;
health remains responsive. The Rust search/index timeout is five minutes, the
FAISS child timeout is one minute, and timed-out submitted storage work may still
finish. Retrying derived indexing is safe and never mutates Markdown.

## Local API and desktop

Both endpoints use the existing authenticated loopback API and UUID validation:

| Request | Body | Result |
| --- | --- | --- |
| `POST /api/v1/vaults/{vault_id}/index` | `{"rebuild": false}` (default false) | Vault/model fingerprint, note/chunk counts, generated/reused/removed counts. |
| `POST /api/v1/vaults/{vault_id}/search` | `{"query": "care for baby vegetables", "limit": 10}` | Vault/model fingerprint and source-attributed ranked hits. |

Search queries must be nonblank UTF-8 text, at most 2000 characters and 220 model
tokens. Limits are strict integers from 1 through 50. Unknown fields, coercions,
invalid UUIDs, closed vaults, and sessions requiring reconciliation are rejected.
The query goes in the JSON body, never a URL. Errors omit credentials, query text,
note content, and underlying exception messages.

The webview uses `semantic_index` and `semantic_search` Tauri commands, scoped to
the main local webview with generated permissions. Rust validates result ownership,
canonical IDs, revisions, source byte ranges and lengths, line ranges, unique chunk
IDs, scores, and index counts. Result snippets are excluded from Rust Debug output.

Open **Semantic search** in the ribbon, enter a query, and choose **Search Notes**.
The panel searches saved content, lists source passages/line numbers/similarities,
and opens results through existing dirty draft safeguards. It provides loading,
empty, model setup, error/retry, and explicit corrupt-index rebuild states. Old
responses are ignored after closing, vault changes, backend generations, or saved
note version changes. Unsaved editor drafts never enter the index. Search and graph
panels share the side-panel space; the editor stays mounted.

## Validation

Mechanics tests use a small explicit encoder to assert cache behavior and failure
atomicity, while still exercising the real FAISS subprocess. Relevance acceptance
uses the actual pinned pretrained model and four paraphrased queries covering
plants, SQL transactions, astronomy and bread baking. All four return their intended
passage at rank one. This is a small regression fixture, not a general retrieval
benchmark or evidence about LLM answer accuracy; Stage 11 owns broader evaluation.

```sh
# Relevance tests are opt-in and never download a model during pytest.
PAGE_TEST_SEMANTIC_MODEL=1 .venv/bin/python -m pytest packages/core -q
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml -- --include-ignored
```

The Rust semantic integration test is explicitly ignored without model preparation;
`--include-ignored` exercises the production bridge against a real Core process,
including rank-one relevance, canonical identities, move reuse, external additions,
deletions, reopening and identical repeated scores. Frontend tests use the real
workspace/controller/editor with only the IPC boundary mocked and cover source
results, dirty draft Cancel/Discard, saved revision invalidation, corrupt-index
rebuild, and stale responses after closing/vault/backend changes.

## Acceptance on macOS — October 10, 2026

Stage 8 acceptance is complete on macOS. Windows remains unverified.

- Core: **891 passed**, including real pretrained relevance and source/chunk/cache
  checks, with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and
  `PAGE_TEST_SEMANTIC_MODEL=1` (34.68 seconds).
- Frontend: **63 passed** across eight files; typecheck and lint passed.
- Rust: **47 unit tests and 3 integration tests passed** with `--include-ignored`,
  including the real semantic bridge. Cargo formatting and Cargo check passed.
- Production build passed. The existing main-bundle size warning remains nonfatal
  (approximately 789 kB minified); the graph remains a separate lazy bundle.
- `pip check` found no broken requirements; `git diff --check` passed.

Native smoke checks used only the disposable test vault. Meaning-based queries
opened the intended gardening and transaction notes by canonical identity. Cancel
preserved a dirty draft; Discard permitted result navigation and loaded exact saved
content. The user inspected search at 1024×720 and 800×600, including queries,
passage previews and navigation, and replied: “Looks and behaves correctly.”
This is human visual acceptance; no automated screen capture is claimed.

Implementation references:
[Sentence Transformer model API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html),
[FAISS cosine similarity](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances),
and the [pinned MiniLM model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41).
