import { useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import type { GraphResponse, DesktopError } from "../core/types";
import { toDesktopError } from "../core/types";
import { backendReady, navigationBlocked, type WorkspaceController, type WorkspaceState } from "../workspace/controller";
import { createKnowledgeGraph } from "../workspace/graph";
import { ErrorText } from "./ErrorText";
import { Icon } from "./Icon";

export function KnowledgeGraph({ controller, state, onClose }: {
  controller: WorkspaceController; state: WorkspaceState; onClose: () => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<{ key: string; graph: GraphResponse | null; error: DesktopError | null } | null>(null);
  const vaultId = state.vault?.id;
  const available = backendReady(state) && !state.vaultBusy && !state.pending && !state.recovery && !state.unknown;
  const accepted = state.document?.accepted;
  // Overlay a newly accepted revision until the note list catches up. Merely
  // selecting a note keeps the same topology and dragged node positions.
  const versions = state.notes?.map((node) => [node.id, node.id === accepted?.id ? accepted.revision : node.revision]);
  const unlisted = accepted && !state.notes?.some((node) => node.id === accepted.id) ? [accepted.id, accepted.revision] : null;
  const key = JSON.stringify([vaultId, state.backend?.generation, versions, unlisted, available, retry]);
  const graph = result?.key === key ? result.graph : null;
  const error = result?.key === key ? result.error : null;
  const selected = state.document?.noteId;
  const blocked = navigationBlocked(state) || state.recovery !== null;
  const latest = useRef({ controller, blocked });
  useEffect(() => { latest.current = { controller, blocked }; });

  useEffect(() => {
    if (!vaultId || !available) return;
    let disposed = false;
    void controller.readGraph(vaultId).then((response) => {
      if (!disposed) setResult({ key, graph: response, error: null });
    }, (cause: unknown) => {
      if (!disposed) setResult({ key, graph: null, error: toDesktopError(cause) });
    });
    return () => { disposed = true; };
  }, [controller, vaultId, available, key]);

  useEffect(() => {
    if (!graph || !container.current) return;
    const instance = createKnowledgeGraph(container.current, graph, (id) => {
      if (!latest.current.blocked) void latest.current.controller.selectNote(id);
    });
    cy.current = instance;
    const observer = new ResizeObserver(() => { instance.resize(); });
    observer.observe(container.current);
    return () => { observer.disconnect(); cy.current = null; instance.destroy(); };
  }, [graph]);

  useEffect(() => {
    const instance = cy.current;
    instance?.nodes().unselect();
    const node = selected ? instance?.getElementById(selected) : undefined;
    if (!node || node.empty()) return;
    node.select();
    // Glide to the open note when it is outside the visible area.
    const view = instance!.extent();
    const { x, y } = node.position();
    if (x < view.x1 || x > view.x2 || y < view.y1 || y > view.y2) {
      instance!.animate({ center: { eles: node } }, { duration: 350, easing: "ease-out-cubic" });
    }
  }, [graph, selected]);

  const paths = new Map(graph?.nodes.map((node) => [node.id, node.relative_path]));
  const outgoing = graph?.links.filter((link) => link.source_note_id === selected) ?? [];
  const backlinks = graph?.links.filter((link) => link.target_note_id === selected) ?? [];
  const selectedPath = selected ? paths.get(selected) : undefined;
  return <aside className="knowledge-panel graph-panel" aria-label="Knowledge graph">
    <header className="knowledge-heading">
      <h2>Knowledge graph</h2>
      {graph && <span className="graph-counts">{graph.nodes.length} notes · {graph.links.length} links</span>}
      <div className="graph-actions">
        <button className="icon-button" aria-label="Refresh Graph" title="Refresh graph" disabled={!available}
          onClick={() => { void controller.refreshFromDisk(); setRetry((value) => value + 1); }}><Icon name="refresh" size={14} /></button>
        <button disabled={!graph} title="Fit all notes" onClick={() => cy.current?.animate({ fit: { eles: cy.current.elements(), padding: 40 } }, { duration: 350 })}>Fit</button>
        <button className="icon-button" onClick={onClose} aria-label="Close graph" title="Close graph"><Icon name="close" size={14} /></button>
      </div>
    </header>
    {!available && <p role="status" className="graph-message">Graph unavailable until Core and the vault are ready.</p>}
    {available && !graph && !error && <p role="status" className="graph-message">Loading graph…</p>}
    {error && <div role="alert" className="graph-message"><ErrorText error={error} /><button onClick={() => setRetry((value) => value + 1)}>Retry Graph</button></div>}
    {graph && <>
      {graph.nodes.length === 0 && <p className="graph-message">No notes yet. Create a note to start linking.</p>}
      <div className="graph-stage">
        <div ref={container} className="graph-canvas" aria-label="Interactive note graph" />
        <p className="graph-legend" aria-hidden="true">Scroll to zoom · drag to move · click a note to open it</p>
      </div>
      <div className="graph-details">
        {selected && <section className="graph-focus" aria-label="Selected note links">
          <h3 title={selectedPath}>{selectedPath?.replace(/\.md$/, "") ?? "This note"}</h3>
          <div className="graph-columns">
            <div>
              <h4>Links from this note</h4>
              {outgoing.length === 0 && <p>No outgoing wiki links.</p>}
              <ul>{outgoing.map((link, index) => <li key={index}>
                {link.target_note_id ? <button disabled={blocked} onClick={() => void controller.selectNote(link.target_note_id!)}>{link.alias || link.target_reference}</button>
                  : <span className="unresolved-link">{link.alias || link.target_reference} · {link.unresolved_reason}</span>}
                <small>Line {link.line}</small>
              </li>)}</ul>
            </div>
            <div>
              <h4>Backlinks</h4>
              {backlinks.length === 0 && <p>No backlinks yet.</p>}
              <ul>{backlinks.map((link, index) => <li key={index}>
                <button disabled={blocked} onClick={() => void controller.selectNote(link.source_note_id)}>{paths.get(link.source_note_id)}</button><small>Line {link.line}</small>
              </li>)}</ul>
            </div>
          </div>
        </section>}
        <details><summary>All notes</summary><ul>{graph.nodes.map((node) => <li key={node.id}>
          <button disabled={blocked} aria-current={node.id === selected ? "true" : undefined} onClick={() => void controller.selectNote(node.id)}>{node.relative_path}</button>
        </li>)}</ul></details>
      </div>
    </>}
  </aside>;
}
