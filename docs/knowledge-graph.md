# Knowledge graph

Page connects notes through wiki links: reference resolution, unresolved references,
backlinks, graph updates and an interactive Cytoscape.js view. Validated on macOS on
October 10, 2026. Windows remains unverified.

## Wiki links and reference resolution

Use `[[Note]]`, `[[folder/Note.md]]`, `[[Note#Heading|Display name]]` or
`![[Note]]`. Embeds contribute a relationship; embedded content is not rendered.
Fragments identify a relationship to the note; scrolling to headings or blocks
is not implemented. `[[#Heading]]` references the current note.

Resolution is case-sensitive and deterministic:

1. `/folder/Note` explicitly starts at the vault root. Paths containing a slash
   otherwise start at the vault root; `./Note` starts in the source note's folder.
2. Bare names prefer a note in the source folder. Otherwise, a unique basename
   anywhere in the vault resolves. Multiple matches remain ambiguous.
3. The `.md` extension is optional. Missing, ambiguous and invalid references
   are kept with a reason; they never receive a real note UUID. Traversal,
   backslashes and URL schemes are not resolved.

The standard-library parser ignores fenced/indented code, inline code, HTML
comments, initial YAML frontmatter and escaped opening brackets. Multiline or
malformed brackets do not form links. This is a focused wiki-link parser, not a
complete CommonMark renderer. Note aliases come from the link's `|label`, not
frontmatter. Note names and paths containing wiki-link delimiters cannot be
addressed by this syntax.

Source line numbers follow CR, LF and CRLF. Repeated links keep their individual
locations; backlinks are directed incoming references. Cycles and self-links
are supported. Renames never rewrite Markdown automatically: a bare basename
can still resolve after a move, while a reference to an obsolete path becomes
unresolved. Recreating a deleted note uses its new canonical ID.

## Core, API and desktop boundaries

`page_core.graph` is pure: immutable snapshots, no filesystem/network/database
I/O and no generated note identities. `LocalVaultService.get_graph` reconciles
external changes, reads current notes through `PersistentVault`, then builds the
snapshot on the existing storage worker. UUIDs remain the canonical persisted
identities used by the note API. Reconciliation updates metadata; source Markdown
bytes are never rewritten by graph reads. An unreadable note or corrupt metadata
produces the existing safe API error rather than silently omitting relationships.

`GET /api/v1/vaults/{vault_id}/graph` returns:

```json
{
  "vault_id": "<canonical vault UUID>",
  "nodes": [{"id": "<canonical note UUID>", "relative_path": "note.md"}],
  "links": [{
    "source_note_id": "<canonical note UUID>",
    "target_reference": "Missing#Heading",
    "target_note_id": null,
    "alias": null,
    "line": 1,
    "unresolved_reason": "missing"
  }]
}
```

Resolved references have `target_note_id` and a null `unresolved_reason`.
The endpoint requires the same authenticated loopback session, UUID validation,
open vault and reconciliation state as note operations. Rust's fixed `graph_read`
command checks the caller and validates graph topology before forwarding it.
Credentials remain in Rust; no second HTTP server or browser-held token is added.

Graph snapshots are rebuilt from current files when requested, avoiding a second
identity registry or stale graph database. This costs a vault scan and note reads
per refresh; there is no filesystem watcher or incremental graph cache. Desktop
refreshes the open panel after saved note changes, list changes, reconciliation
and backend restart. Unsaved drafts do not change graph relationships. Changes in
another editor are reflected through Refresh Graph/Refresh from Disk.

## Graph workspace

The ribbon's Knowledge graph button opens a panel alongside the editor. The
[Cytoscape.js](https://js.cytoscape.org/) canvas supports node dragging, pan, zoom
and Fit. Solid violet nodes are notes; dashed amber nodes are unresolved references.
Arrows point from the source note to its target. Selecting a note highlights its
node and shows outgoing links and backlinks. Clicking a real node, an outgoing
link, a backlink or a note in All notes navigates through the existing dirty guard.
Unresolved nodes cannot navigate or create files. All notes and relationship lists
provide keyboard-accessible navigation alongside the canvas.

The graph module loads lazily. On narrow windows, the Files sidebar is hidden
while the graph is open to preserve editor space. Closing the graph restores it.
The editor remains mounted, preserving drafts and undo. Loading/error states
provide retry; old responses are ignored after view closure or vault/session
changes, and graphs from a previous vault are never shown as current.

Dependency: `cytoscape` 3.34.3, pinned with `package-lock.json`; its bundled types
require no additional type package. No new Python or Rust dependencies.

## Validation

- Core syntax/resolution tests: excluded syntax, Unicode, separator locations,
  aliases, fragments, ambiguity, canonical identities, moves, deletion, immutable
  validation and deterministic ordering.
- Real API/storage tests: empty graph, CRUD, external changes, stable UUIDs after
  reopen, unchanged source bytes, closed sessions and malformed identifiers.
- Rust tests: authenticated fixed route, topology/nullable DTO validation and
  a graph read through the real production Python subprocess.
- Cytoscape tests: real headless topology, directed neighbors, repeated edges,
  node tap navigation and unresolved-node refusal. DOM tests replace only the
  canvas renderer with Cytoscape's headless mode, retaining actual events,
  controller behavior, dirty guards, backlinks, refresh, retry and cleanup.

For native acceptance, open a disposable vault with `[[Target]]` and a missing
reference. Check node navigation in both directions, selected-node highlighting,
backlink/outgoing buttons, dirty Save/Discard/Cancel, graph refresh after edits
and deletion, drag/pan/zoom/Fit, and readability at 1024×720 and 800×600.

## Acceptance results — October 10, 2026

All required checks passed on macOS: 831 Core tests, 59 frontend tests,
TypeScript checks, ESLint, production build, Cargo format check and Cargo check.
Rust tests passed too: 46 unit tests and two integration tests. The build retains
its nonfatal warning for the existing 785 kB editor bundle; the graph loads in a
separate 440 kB bundle.

Native tests in the disposable vault verified graph loading and note/link counts,
outgoing-link and backlink navigation, dirty Cancel retaining a draft, dirty
Discard proceeding to the target, Fit, saved-link updates, resolving an external
target after Refresh Graph, and deletion while the graph is open.

The user inspected the graph at the requested window sizes and accepted node
dragging, pan, zoom, note-node navigation and the layout ("Looks and behaves
correctly"). This is human interaction/visual acceptance, not an automated
screenshot claim. Screen capture permission remains unavailable.
