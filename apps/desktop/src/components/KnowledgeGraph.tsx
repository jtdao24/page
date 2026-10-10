import { useEffect, useRef, useState } from "react";
import type { Core } from "cytoscape";
import type { GraphResponse, DesktopError } from "../core/types";
import { toDesktopError } from "../core/types";
import { backendReady, navigationBlocked, type WorkspaceController, type WorkspaceState } from "../workspace/controller";
import { createKnowledgeGraph } from "../workspace/graph";
import { ErrorText } from "./ErrorText";

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
    if (selected) instance?.getElementById(selected).select();
  }, [graph, selected]);

  const paths = new Map(graph?.nodes.map((node) => [node.id, node.relative_path]));
  const outgoing = graph?.links.filter((link) => link.source_note_id === selected) ?? [];
  const backlinks = graph?.links.filter((link) => link.target_note_id === selected) ?? [];
  return <aside className="knowledge-panel" aria-label="Knowledge graph">
    <header className="knowledge-heading"><h2>Knowledge graph</h2><button onClick={onClose} aria-label="Close graph">×</button></header>
    <p className="knowledge-hint">Saved wiki links · arrows point to referenced notes</p>
    <div className="graph-actions">
      <button disabled={!available} onClick={() => { void controller.refreshFromDisk(); setRetry((value) => value + 1); }}>Refresh Graph</button>
      <button disabled={!graph} onClick={() => cy.current?.fit(undefined, 28)}>Fit</button>
    </div>
    {!available && <p role="status">Graph unavailable until Core and the vault are ready.</p>}
    {available && !graph && !error && <p role="status">Loading graph…</p>}
    {error && <div role="alert"><ErrorText error={error} /><button onClick={() => setRetry((value) => value + 1)}>Retry Graph</button></div>}
    {graph && <>
      <p className="graph-counts">{graph.nodes.length} notes · {graph.links.length} links</p>
      {graph.nodes.length === 0 && <p>No notes yet. Create a note to start linking.</p>}
      <div ref={container} className="graph-canvas" aria-label="Interactive note graph" />
      <div className="graph-details">
        <details><summary>All notes</summary><ul>{graph.nodes.map((node) => <li key={node.id}>
          <button disabled={blocked} aria-current={node.id === selected ? "true" : undefined} onClick={() => void controller.selectNote(node.id)}>{node.relative_path}</button>
        </li>)}</ul></details>
        {selected && <>
          <h3>Links from this note</h3>
          {outgoing.length === 0 && <p>No outgoing wiki links.</p>}
          <ul>{outgoing.map((link, index) => <li key={index}>
            {link.target_note_id ? <button disabled={blocked} onClick={() => void controller.selectNote(link.target_note_id!)}>{link.alias || link.target_reference}</button>
              : <span className="unresolved-link">{link.alias || link.target_reference} · {link.unresolved_reason}</span>}
            <small>Line {link.line}</small>
          </li>)}</ul>
          <h3>Backlinks</h3>
          {backlinks.length === 0 && <p>No backlinks yet.</p>}
          <ul>{backlinks.map((link, index) => <li key={index}>
            <button disabled={blocked} onClick={() => void controller.selectNote(link.source_note_id)}>{paths.get(link.source_note_id)}</button><small>Line {link.line}</small>
          </li>)}</ul>
        </>}
      </div>
    </>}
  </aside>;
}
