# Page

A local-first workspace for your Markdown notes.

Page gives your notes a quiet place to live: a familiar desktop layout, a folder
sidebar, and a focused Markdown editor. Your files stay on your computer, in a
vault you choose.

## Your notes, in your hands

Notes are ordinary `.md` files. Open a vault, bring in existing Markdown files,
and organize them in folders. You can continue using those files outside Page;
the files remain the source of truth.

## A focused writing workspace

- **Browse your vault.** Navigate nested folders and switch between open vaults.
- **Write in Markdown.** Edit with syntax highlighting, undo and redo, and a dark
  interface with subtle violet accents.
- **Save when you're ready.** Save explicitly with the button or Cmd+S. Page asks
  what to do with an unsaved draft before you leave it.
- **Organize your notes.** Create notes, rename them, move them between folders,
  and confirm permanent deletion.
- **Handle changes on disk.** Refresh after external edits, review conflicts,
  and choose whether to reload the file or keep your draft.
- **Pick up where you left off.** Page remembers your recent vaults and last
  selected note.

## Built around local files

The current note workflow runs locally and needs no cloud account. Page preserves
Unicode text and existing uniform line endings. If a note disappears from disk,
you can retain its draft and save it as a new note.

## Looking ahead

Page's longer-term direction is an AI-native knowledge workspace: connected notes,
a knowledge graph, and context selection for language models. Those capabilities
are planned. The current app focuses on local Markdown editing and organization.

## Availability

The current desktop workflow is validated on macOS. Packaged downloads are not
available yet; Windows support is planned.

For setup instructions, see [Developing Page](docs/development.md).

## Landing page and graph preview

This branch also retains Page's download website and experimental graph workspace.
Run `npm run dev` and visit `/landing.html` for the landing page or `/graph.html`
for the beige-and-green graph, reading tabs, and split panes. The default `/` and
Tauri window use the Stage 6 editing workspace described above. The graph preview's
optional ingestion service remains separate from the Stage 6 core process.

After building an Apple Silicon `Page.app`, run `npm run build` and
`npm run landing:export` to create a standalone website with a development ZIP
download. `npm run landing:preview` serves it at `http://localhost:4173`.
The Python core still requires separate installation; no public installer is
published by this export. See [the landing page guide](docs/landing-page.md) and
[the graph workspace guide](docs/graph-workspace.md).
