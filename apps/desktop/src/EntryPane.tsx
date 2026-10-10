import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { collectionOf } from "./library";
import type { ContextNote } from "./library";
import { loadNote, noteHeadings, previewDocument } from "./noteReader";
import type { NoteDocument } from "./noteReader";
import "./reader.css";

type ReaderState = { status: "loading" } | { status: "error"; message: string }
  | { status: "ready"; document: NoteDocument };
type HtmlNode = { type: string; children?: HtmlNode[]; properties?: Record<string, unknown> };

// Multiple notes stay mounted in tabs. Namespace generated footnote IDs and
// their references so navigation and accessibility never target another tab.
function scopeMarkdownIds(prefix: string) {
  return () => (tree: HtmlNode) => {
    const visit = (node: HtmlNode) => {
      const props = node.properties;
      if (props) {
        if (typeof props.id === "string") props.id = `${prefix}-${props.id}`;
        if (typeof props.href === "string" && props.href.startsWith("#")) props.href = `#${prefix}-${props.href.slice(1)}`;
        if (Array.isArray(props.ariaDescribedBy)) props.ariaDescribedBy = props.ariaDescribedBy.map((id) => `${prefix}-${id}`);
      }
      node.children?.forEach(visit);
    };
    visit(tree);
  };
}

export function EntryPane({ note, session, preview, onAsk }: {
  note: ContextNote; session: string | null; preview: boolean; onAsk: () => void;
}) {
  const pane = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<ReaderState>(() => preview ? { status: "ready", document: previewDocument(note) }
    : session ? { status: "loading" } : { status: "error", message: "Connect your vault to read this entry." });
  const [source, setSource] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const prefix = `entry-${note.id}`;
  useEffect(() => {
    if (preview || !session) return;
    const controller = new AbortController();
    void loadNote(note, session, controller.signal).then((document) => {
      if (!controller.signal.aborted) setState({ status: "ready", document });
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setState({ status: "error", message: cause instanceof Error ? cause.message : "Couldn’t open this entry. Please try again." });
    });
    return () => controller.abort();
  }, [note, session, preview, attempt]);
  const content = state.status === "ready" ? state.document.content : "";
  const headings = useMemo(() => noteHeadings(content, `${prefix}-section`), [content, prefix]);
  const components = useMemo<Components>(() => {
    const jumpTo = (id: string) => {
      const target = document.getElementById(id);
      if (target && pane.current?.contains(target)) { target.scrollIntoView({ block: "start" }); target.focus({ preventScroll: true }); }
    };
    return {
      h1: ({ node, ...props }) => <h1 {...props} id={node?.position ? `${prefix}-section-${node.position.start.line}` : props.id} tabIndex={-1} />,
      h2: ({ node, ...props }) => <h2 {...props} id={node?.position ? `${prefix}-section-${node.position.start.line}` : props.id} tabIndex={-1} />,
      h3: ({ node, ...props }) => <h3 {...props} id={node?.position ? `${prefix}-section-${node.position.start.line}` : props.id} tabIndex={-1} />,
      h4: ({ node, ...props }) => <h4 {...props} id={node?.position ? `${prefix}-section-${node.position.start.line}` : props.id} tabIndex={-1} />,
      h5: ({ node, ...props }) => <h5 {...props} id={node?.position ? `${prefix}-section-${node.position.start.line}` : props.id} tabIndex={-1} />,
      h6: ({ node, ...props }) => <h6 {...props} id={node?.position ? `${prefix}-section-${node.position.start.line}` : props.id} tabIndex={-1} />,
      a: ({ href, children }) => href?.startsWith("#") ? <a href={href} onClick={(event) => {
        event.preventDefault(); try { jumpTo(decodeURIComponent(href.slice(1))); } catch { /* Invalid fragment. */ }
      }}>{children}</a> : <span className="reader-link" title={href}>{children}</span>,
      img: ({ alt }) => <span className="reader-image">▧ {alt || "Image attachment"}</span>,
    };
  }, [prefix]);
  const idPlugin = useMemo(() => scopeMarkdownIds(prefix), [prefix]);
  // Tab switches and core status polling must not reparse every open document.
  const renderedMarkdown = useMemo(() => <Markdown skipHtml remarkPlugins={[remarkGfm]}
    rehypePlugins={[idPlugin]} components={components}>{content}</Markdown>, [content, components, idPlugin]);
  const updated = new Date(state.status === "ready" ? state.document.updated_at : note.updated_at);
  const refresh = () => { setState({ status: "loading" }); setAttempt((previous) => previous + 1); };
  return <div className="entry-pane" ref={pane}>
    <header className="entry-header"><div><p>{collectionOf(note)} / {preview ? "Sample entry" : "Local Markdown"}</p><h1>{note.title}</h1></div>
      <div className="entry-actions"><button type="button" aria-pressed={source} disabled={state.status !== "ready"} onClick={() => setSource(!source)}>{source ? "Reading view" : "Markdown source"}</button>
        {!preview && session && <button type="button" disabled={state.status === "loading"} onClick={refresh}>Refresh entry</button>}
        <button type="button" onClick={onAsk}>Ask about this entry ↗</button></div></header>
    <div className="entry-provenance"><span>{state.status === "ready" ? state.document.path : note.path}</span>
      {!Number.isNaN(updated.getTime()) && <time dateTime={updated.toISOString()}>Updated {updated.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}</time>}</div>
    {preview && <p className="reader-preview-label">Sample Markdown entry. Connect your vault to read your own notes.</p>}
    <div className="entry-document-layout">
      <div className="entry-document" aria-busy={state.status === "loading"}>
        {state.status === "loading" && <div className="reader-message" role="status"><h2>Opening your entry…</h2><p>Reading its Markdown file.</p></div>}
        {state.status === "error" && <div className="reader-message" role="alert"><h2>This entry couldn’t be opened.</h2><p>{state.message}</p>{session && <button className="button button-primary" onClick={refresh}>Try again</button>}</div>}
        {state.status === "ready" && (content.trim() ? source ? <pre className="reader-source" tabIndex={0} aria-label="Markdown source">{content}</pre>
          : <article className="reader-markdown" aria-label="Entry text">{renderedMarkdown}</article>
          : <div className="reader-message"><h2>A blank page, full of possibility.</h2><p>This Markdown entry is empty.</p></div>)}
      </div>
      <aside className="entry-outline"><h2>Contents</h2><nav aria-label="Entry contents">{headings.length ? headings.map((heading) => <button type="button" key={heading.id}
        className={heading.level > 1 ? "is-subsection" : ""} disabled={source} onClick={() => {
          const target = document.getElementById(heading.id); target?.scrollIntoView({ block: "start" }); target?.focus({ preventScroll: true });
        }}>{heading.title}</button>) : <span>{state.status === "loading" ? "Loading…" : "No headings in this entry"}</span>}</nav></aside>
    </div>
  </div>;
}
