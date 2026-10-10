# Stage 4 review response

The replacement PR is based on current main and is limited to SQLite
metadata persistence. Earlier ingestion and later frontend work are preserved
on `caiden`, outside this PR, as explicitly requested.

| Finding | Resolution in this PR |
| --- | --- |
| Stage 4 scope and missing persistence | Versioned migrations, metadata CRUD, persistent independent note UUIDs, stable creation timestamps, transaction/savepoint rollback, and external reconciliation. No later-stage implementation. |
| Standard install skipped ingestion tests | No ingestion dependencies are introduced. A fresh Python 3.12 environment using unchanged pinned dev requirements collects every Stage 4 test. |
| Content/ordinal-derived chunk IDs | No chunk generation. Stage 2's Chunk value model remains unchanged. Later chunk UUID reconciliation remains required before indexing lands. |
| Cache confidentiality | Owner-only directories/database/SQLite auxiliaries, ownership checks, symlink/hard-link rejection, permission tightening, and privacy tests. No full note text is cached. Windows access fails closed pending verified ACL support. |
| Stale frontend requests after disconnect | No local API or connection/indexing frontend in this PR. The saved later-stage implementation needs request invalidation before its own PR. |
| Missing desktop behavior coverage | No desktop behavior changes. Adds metadata/adapter behavior tests. Polling/action/error/disconnect tests remain prerequisites for later desktop integration. |

The new database is `.page/metadata/notes.sqlite3`. The deferred semantic cache
on `caiden` is not reused, imported, migrated, or claimed as Stage 4 persistence.
Main never received that implementation, so no existing main database requires
a destructive conversion. Notes and the existing Stage 3 manifest remain
authoritative; source files are adopted without rewriting them.

See [sqlite-metadata.md](sqlite-metadata.md) for contracts, recovery, reconciliation,
and platform limits. Validation results are reported in the PR description.
