import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";
import { CORE_URL } from "./useCore";
import type { ContextNote } from "./library";

export interface NoteDocument {
  id: string;
  path: string;
  content: string;
  updated_at: string;
}

export async function loadNote(note: ContextNote, token: string, signal: AbortSignal): Promise<NoteDocument> {
  const response = await fetch(`${CORE_URL}/api/context/${encodeURIComponent(note.id)}`, {
    headers: { Authorization: `Bearer ${token}` },
    signal: AbortSignal.any([signal, AbortSignal.timeout(8000)]),
  });
  if (!response.ok) {
    if (response.status === 401) throw new Error("Your vault connection has expired. Reconnect in Vault settings.");
    if (response.status === 404) throw new Error("This note could not be opened. Index your vault changes and try again. If your core service is older, restart it with the updated version.");
    if (response.status === 413) throw new Error("This note is too large for the reader (1 MiB maximum). You can still read the original Markdown file in your vault.");
    throw new Error("Couldn’t read this note. Check that its Markdown file is accessible, then try again.");
  }
  const body: unknown = await response.json();
  const document = (body as { note?: NoteDocument } | null)?.note;
  if (!document || document.id !== note.id || typeof document.path !== "string"
    || typeof document.content !== "string" || typeof document.updated_at !== "string") {
    throw new Error("The core service returned an unreadable note. Update the service and try again.");
  }
  return document;
}

export function noteHeadings(content: string, prefix = "page-section") {
  const tree = unified().use(remarkParse).use(remarkGfm).parse(content);
  const headings: { id: string; title: string; level: number }[] = [];
  // Both parser and renderer use source line numbers, including setext headings.
  const text = (node: { type: string; value?: string; alt?: string | null; children?: typeof tree.children }): string =>
    node.value ?? node.alt ?? node.children?.map(text).join("") ?? "";
  const visit = (nodes: typeof tree.children) => {
    for (const node of nodes) {
      if (node.type === "heading") headings.push({ id: `${prefix}-${node.position?.start.line}`,
        title: text(node), level: node.depth });
      if ("children" in node) visit(node.children as typeof tree.children);
    }
  };
  visit(tree.children);
  return headings;
}

export function previewDocument(note: ContextNote): NoteDocument {
  return { id: note.id, path: note.path, updated_at: note.updated_at,
    content: `# ${note.title}\n\n${note.excerpt}\n\n## A thought to keep\n\n> A note does not have to be finished to be worth keeping.\n\n## In the margins\n\n- Notice what catches your attention.\n- Leave room for a question.\n- Return when you have something to add.\n\n---\n\n*This is a sample note in the Page preview library.*` };
}
