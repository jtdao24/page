# Entry graph and workspace tabs

The Tauri 2 workspace displays each indexed Markdown note as a node keyed by its
existing UUID. The compact icon ribbon, collapsible file sidebar, local account
controls, indexing controls, and question draft remain available.

The workspace uses a parchment and tan palette with forest green selected tabs,
sage navigation highlights, and warm ink for text. Shared colors live in the
`--workspace-*` tokens in `workspace.css`; graph collections use a separate
earth-tone palette in `graph.ts`.

## Graph

The graph uses a deterministic spiral layout and collection colors. Its edges
connect entries in the same collection (first vault folder, or **Notes** for
root-level files). These visual associations are explicitly labeled in the UI;
they are not semantic similarities, parsed wiki links, or learned relationships.
No neural model or graph-processing backend is introduced by this frontend.
Every node is a real entry; there are no invented hub nodes. The edge count grows
linearly with the number of notes rather than connecting every possible pair.

Search, collection filters, and recent entries apply to the graph. Filtering
keeps remaining nodes in their original positions. Pan by dragging the background,
use the zoom buttons, or reset the view. Nodes are native buttons with complete
accessible names and can be opened with Enter/Space. Preview entries are labeled.

## Tabs and note content

Selecting a node or sidebar file opens its entry in a workspace tab. Opening an
existing entry selects its tab instead of duplicating it. The permanent **Graph**
tab restores the current graph, filters, and camera. Entry panels stay mounted
while hidden, preserving their source mode, loaded content, and independent
scroll containers. Closing a tab aborts its pending read. Closing the active tab
selects an adjacent entry, or the graph if no entries remain; closing a background
tab leaves the active entry selected.

Tabs support arrow keys, Home/End, and Delete to close an entry. The graph tab
cannot be closed. Tabs are scoped to the current vault connection and preview
mode; a connection change unmounts the old panels and aborts pending reads.
Entry content is never persisted to browser storage. Only the sidebar layout
preference and existing unsent question draft are saved locally.

### Split view

Drag a tab into the reading area, then release over **Split to left** or
**Split to right** to see two panels together. Each pane has its own tab strip
and selection. Drag a tab to the other pane or its tab strip to move it. Closing
or moving the last tab out of a pane returns to one pane. Graph can be moved but
cannot be closed. Entries remain unique across both panes; reopening one selects
it where it already lives. New entries open in the pane most recently selected
or used for reading. The split icon beside each tab strip also provides a
keyboard-accessible way to split or move the selected tab.

Panels remain siblings in the React tree and use CSS grid to change position.
Moving a tab retains its mounted reader, source mode, scroll position, and any
pending request. Each visible panel scrolls independently. Narrow windows stack
the panes, and the reader outline adapts to the pane width. The layout is scoped
to the connection and is not saved to disk.

Only drags started by this workspace in the current session can move tabs;
external and stale-session drops are ignored. `dragDropEnabled: false` lets
the frontend handle HTML tab dragging, including on Windows, as required by
[Tauri's configuration documentation](https://v2.tauri.app/reference/config/#dragdropenabled).
Native file-drop events are disabled; file-drop ingestion is not implemented.

Entries display complete Markdown, source view, contents, relative file path,
and modification date. Heading and generated footnote IDs are namespaced by
entry UUID, so navigating one note never targets another mounted tab. Refresh
reads the current file again. **Ask about this entry** returns to the existing
local draft and leaves the entry tab open; it does not send an AI request.

## Existing source endpoint

The authenticated loopback bridge's read-only endpoint remains
`GET /api/context/{note_uuid}`. It returns
`{"note": {"id", "path", "content", "updated_at"}}`.

The index resolves an existing UUID to its managed relative path and reuses the
vault's no-follow regular-file and UTF-8 checks. Content comes from the original
Markdown source, not reconstructed chunks. Reads do not load an embedding model
or update the index. External edits are readable immediately; index external
moves/deletions to refresh ID mapping. The bridge still starts separately and
requires restarting after installing the source-reading endpoint.

The reader limit remains 1 MiB. Unknown/deleted sources return 404, malformed
IDs 400, oversized files 413, and inaccessible/invalid UTF-8 sources 422. Responses
retain token/origin protections and `no-store`. Loading, retry, and empty-note
states are explicit. A failed connected read never substitutes preview content.

Raw HTML is skipped. Images/attachments and external/relative links are shown as
text rather than loading remote content or navigating the webview. Wiki-link
resolution, editing, and external attachment opening remain future work. Source
view exposes the original text, including unsupported reading-view syntax.

## Validation

Frontend tests cover graph membership, edge meaning and deterministic layout,
filtering, zoom/reset, node keyboard activation, tab creation/reuse/switching/
closing, source-state retention, full-note loading, safe rendering, errors/empty
notes, canceled and late reads, connection changes, cross-tab heading/footnote
navigation, question drafts, compact sidebar controls, left/right splitting,
independent pane selection, tab transfer, empty-pane collapse, canceled/invalid
drags, keyboard splitting, and preservation of pending reads. Native rendered layout
and touch/pan behavior still require visual verification in Tauri.
