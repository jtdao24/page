import { useEffect, useRef, useState } from "react";
import { type DesktopError, type SourceKind, type SourceResponse, toDesktopError } from "../core/types";
import type { WorkspaceController } from "../workspace/controller";
import { ErrorText } from "./ErrorText";
import { Icon } from "./Icon";

export interface OpenSource {
  id: string;
  relativePath: string;
  kind: SourceKind;
  /** Line range to reveal and highlight, from a search hit or citation. */
  lines?: [number, number];
}

const LINE_HEIGHT = 21;
const LABEL: Record<SourceKind, string> = { pdf: "PDF", code: "Code", text: "Text" };

/** Read-only view of a source's extracted text, with line numbers. */
export function SourceViewer({ controller, vaultId, source, onClose }: {
  controller: WorkspaceController; vaultId: string; source: OpenSource; onClose: () => void;
}) {
  const [result, setResult] = useState<{ id: string; source?: SourceResponse; error?: DesktopError } | null>(null);
  const [retry, setRetry] = useState(0);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let live = true;
    controller.readSource(vaultId, source.id).then(
      (value) => { if (live) setResult({ id: source.id, source: value }); },
      (cause: unknown) => { if (live) setResult({ id: source.id, error: toDesktopError(cause) }); });
    return () => { live = false; };
  }, [controller, vaultId, source.id, retry]);
  const loaded = result?.id === source.id ? result : null;
  const text = loaded?.source?.content ?? "";
  const lines = text === "" ? [] : text.replace(/\n$/, "").split("\n");
  const [start, end] = source.lines ?? [0, 0];

  useEffect(() => {
    if (!loaded?.source || start === 0 || !scroller.current) return;
    scroller.current.scrollTop = Math.max(0, (start - 4) * LINE_HEIGHT);
  }, [loaded?.source, start]);

  return <section className="source-viewer" aria-label={`Source: ${source.relativePath}`}>
    <header className="source-header">
      <Icon name={source.kind} size={16} />
      <span className="source-path" title={source.relativePath}>{source.relativePath}</span>
      <span className="source-badge">{LABEL[source.kind]} · read-only</span>
      <button className="icon-button" aria-label="Close source" title="Close" onClick={onClose}><Icon name="close" size={14} /></button>
    </header>
    {!loaded && <p role="status" className="source-message">Reading {source.relativePath}…</p>}
    {loaded?.error && <div role="alert" className="source-message">
      <ErrorText error={loaded.error} /><button onClick={() => setRetry((value) => value + 1)}>Try Again</button>
    </div>}
    {loaded?.source && lines.length === 0 && <p className="source-message">
      {source.kind === "pdf" ? "This PDF has no extractable text (it may be scanned images)." : "This file is empty."}
    </p>}
    {lines.length > 0 && <div ref={scroller} className="source-scroll">
      <div className="source-body" style={{ lineHeight: `${LINE_HEIGHT}px` }}>
        {start > 0 && <div className="source-highlight" aria-hidden="true"
          style={{ top: (start - 1) * LINE_HEIGHT, height: (end - start + 1) * LINE_HEIGHT }} />}
        <pre className="source-gutter" aria-hidden="true">{lines.map((_, index) => index + 1).join("\n")}</pre>
        <pre className="source-text" tabIndex={0}>{lines.join("\n")}</pre>
      </div>
    </div>}
  </section>;
}
