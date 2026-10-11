/** Starter notes for a sample vault; each one teaches a feature and links to the others. */
export const SAMPLE_NOTES: readonly { path: string; content: string }[] = [
  { path: "Welcome to Page.md", content: `# Welcome to Page 👋

This vault is a normal folder on your Mac. Every note is a plain Markdown file you own.

## Try these
- **Write.** Click anywhere in this note and type. Save with ⌘S.
- **Link.** Wrap a note's name in double brackets, like [[Linking notes]].
- **See connections.** Click **Graph** in the sidebar.
- **Ask.** Press ⌘K and ask "how do I add a PDF?" (needs a Gemini key).
- **Bring sources.** Read [[Sources and websites]].

When you're ready, create your own note with ⌘N.
` },
  { path: "Linking notes.md", content: `# Linking notes

Type [[ and a note's name to link it, for example [[Welcome to Page]].
Links appear as lines in the **Graph**, and every note lists its backlinks there.
A link to a note that doesn't exist yet, like [[My next idea]], shows as a dashed node until you create it.
` },
  { path: "Asking questions.md", content: `# Asking questions

The box at the bottom of every note asks your notes a question.
Page finds the most relevant passages, sends only those to Gemini, and the answer cites them as numbers you can click.

Add your Gemini API key with the key button in that box. Back to [[Welcome to Page]].
` },
  { path: "Sources and websites.md", content: `# Sources and websites

Page also reads **PDFs, code and text files** you put in this folder. They appear in Files with their own icons and are searchable, but never changed.

To keep a web page, click **Add website** in the sidebar and paste its address. Page saves a readable copy as a note under web/.

See also [[Asking questions]].
` },
  { path: "ideas/Coffee notes.md", content: `# Coffee notes

A double espresso uses about 18 g of coffee and takes about 25–30 seconds.
Grind finer if it runs fast, coarser if it runs slow.

Try asking: "how long should an espresso take?" — see [[Asking questions]].
` },
];
