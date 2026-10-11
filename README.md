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
  interface with soft blue accents.
- **Save when you're ready.** Save explicitly with the button or Cmd+S. Page asks
  what to do with an unsaved draft before you leave it.
- **Organize your notes.** Create notes, rename them, move them between folders,
  and confirm permanent deletion.
- **Handle changes on disk.** Refresh after external edits, review conflicts,
  and choose whether to reload the file or keep your draft.
- **Connect your ideas.** Link notes with `[[wiki links]]`, follow backlinks,
  and explore their relationships in an interactive knowledge graph.
- **Find notes by meaning.** Search saved passages with a local pretrained model,
  then open the source note from the results.
- **Pick up where you left off.** Page remembers your recent vaults and last
  selected note.

## Built around local files

The current note workflow runs locally and needs no cloud account. Page preserves
Unicode text and existing uniform line endings. If a note disappears from disk,
you can retain its draft and save it as a new note.

## Looking ahead

Page is becoming an AI-native knowledge workspace. Besides local Markdown editing,
relationships between notes and semantic search, you can now ask questions about your
notes with Gemini: Page sends only the most relevant passages, within a token budget
you choose, and the answer cites the notes it used.

Your knowledge isn't limited to Markdown: PDFs, code and text files in the vault
folder are searchable too, and you can save websites as notes.

AI agents such as Claude Code can use the same context engine through Page's MCP
server, which finds and budgets the relevant passages from your notes, with sources.

## Availability

Page can be built as an installable macOS app (Apple silicon, macOS 14 or later)
that includes everything it needs, with no Python setup. See
[packaging](docs/packaging.md). Signed downloads aren't published yet, and Windows
support is planned.

For setup instructions, see [Developing Page](docs/development.md).
