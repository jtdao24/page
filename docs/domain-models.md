# Domain Models

Specification for `page_core.domain`. The source of truth is
`packages/core/src/page_core/domain/models.py`.

## Conventions

- All models are frozen, slotted dataclasses. They have no mutating methods, and a
  change produces a new value (for example via `dataclasses.replace`).
- Validation runs in `__post_init__`. A wrong type raises `TypeError` and a well-typed
  but invalid value raises `ValueError`. Inputs are never coerced or normalized.
- `bool` is rejected wherever an `int` is required.
- Equality is by value across all fields. Entity identity is the `id` field, so to
  ask "is this the same note?", compare `id`s.

## Models

### Vault

A local knowledge vault (metadata only).

| Field       | Type           | Invariant                         |
| ----------- | -------------- | --------------------------------- |
| `id`        | `UUID`         | Stable identity                   |
| `name`      | `str`          | Not empty or whitespace-only      |
| `root_path` | `pathlib.Path` | Absolute; never checked on disk   |

Moving a vault changes `root_path`, not `id`. Construction does not touch the
filesystem and does not create directories.

### Note

A Markdown document in a vault.

| Field           | Type                    | Invariant                                     |
| --------------- | ----------------------- | --------------------------------------------- |
| `id`            | `UUID`                  | Stable identity                               |
| `vault_id`      | `UUID`                  | Owning vault                                  |
| `relative_path` | `PurePosixPath`         | See [Markdown paths](#markdown-paths)          |
| `content`       | `str`                   | May be empty                                  |
| `created_at`    | `datetime`              | Timezone-aware                                |
| `updated_at`    | `datetime`              | Timezone-aware, `updated_at >= created_at`    |

Renaming or moving a note changes `relative_path`, not `id`.

### Link

A directed reference from one note to another.

| Field              | Type           | Invariant                                  |
| ------------------ | -------------- | ------------------------------------------ |
| `source_note_id`   | `UUID`         | Note containing the reference              |
| `target_reference` | `str`          | Not empty or whitespace-only; kept verbatim |
| `target_note_id`   | `UUID \| None` | `None` while the target is unresolved      |

Only the forward direction is stored. Backlinks are derived from links, not duplicated.

### Chunk

A contiguous span of a note for indexing and retrieval.

| Field         | Type          | Invariant                     |
| ------------- | ------------- | ----------------------------- |
| `id`          | `UUID`        | Stable identity               |
| `note_id`     | `UUID`        | Source note                   |
| `ordinal`     | `int`         | `>= 0`, position within note  |
| `text`        | `str`         | Not empty                     |
| `start_byte`  | `int`         | `>= 0`                        |
| `end_byte`    | `int`         | `> start_byte`                |
| `token_count` | `int \| None` | `None` or `>= 0`              |

### ContextResult

An assembled context package for an LLM.

| Field             | Type                 | Invariant                     |
| ----------------- | -------------------- | ----------------------------- |
| `context_text`    | `str`                | May be empty                  |
| `selected_chunks` | `tuple[Chunk, ...]`  | Tuple of `Chunk`; may be empty |
| `token_count`     | `int`                | `>= 0`, `<= token_budget`     |
| `token_budget`    | `int`                | `> 0`                         |

The result keeps the selected `Chunk` objects so every part of the context can be
traced back to a note and byte span.

## Relationships

```
Vault 1 ── * Note            Note.vault_id
Note  1 ── * Link (source)   Link.source_note_id
Note  1 ── * Link (target)   Link.target_note_id, optional
Note  1 ── * Chunk           Chunk.note_id
ContextResult ── * Chunk     ContextResult.selected_chunks
```

Relationships are held by ID, except that `ContextResult` embeds its chunks. The models
do not enforce cross-object integrity (for example, that a `vault_id` exists); that
belongs to the layers that own collections of objects.

## Stable identity

- Every `Vault`, `Note` and `Chunk` has a `UUID` assigned once and never derived from a
  name, path or content.
- Renaming, moving or editing changes fields other than `id`.
- `Link` and `ContextResult` are values without their own identity.

## Markdown paths

`Note.relative_path` is the portable, platform-independent location of a note inside
its vault. `validate_note_path(path)` applies the same rules to a path on its own.

- It must be a `PurePosixPath`. Concrete `Path` objects and Windows paths are rejected
  so that domain objects never carry filesystem-capable or platform-specific paths.
- It must be relative, non-empty, and end in lowercase `.md`.
- `..` components are rejected.
- `\`, `:` and NUL are rejected, because they change a path's meaning on Windows or at
  the OS boundary.
- `PurePosixPath` itself collapses repeated `/` and `.` segments when it is built.
  Mapping to native paths belongs to the filesystem layer.

## Byte offsets

`Chunk` locations are UTF-8 byte offsets into the note's Markdown file, as a half-open
interval `[start_byte, end_byte)`. For example, `"café"` spans 5 bytes. Byte offsets
are unambiguous across languages and tools, and let retrieval results point at exact
spans in the source file. The model does not check that `text` matches the span,
because a chunk's text may later be normalized; span verification belongs to chunking.

## Domain boundaries

`page_core.domain` depends only on the Python standard library. It does not import or
initialize UI frameworks, web frameworks, databases, file I/O, embedding or ML
libraries, LLM providers, MCP, or network services, and it has no serialization layer.
Tests enforce that importing it loads no infrastructure modules and that constructing
models performs no I/O.

## Built elsewhere

The domain layer only defines the types. Everything else lives in other modules:

| Concern | Covered in |
|---|---|
| Reading and writing vaults and notes on disk | [filesystem-vault.md](filesystem-vault.md) |
| Persistence, repositories, serialization | [sqlite-metadata.md](sqlite-metadata.md) |
| API exposure | [local-api.md](local-api.md) |
| Markdown parsing, link resolution, backlinks | [knowledge-graph.md](knowledge-graph.md) |
| Chunking, embeddings, retrieval | [semantic-search.md](semantic-search.md) |
| Neural ranking | [neural-ranking.md](neural-ranking.md) |
| Token counting and context selection | [context-optimization.md](context-optimization.md) |
