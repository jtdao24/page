import { useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { collectionOf } from "./library";
import type { ContextNote } from "./library";
import { collectionColor, entryGraph } from "./graph";
import "./graph.css";

export function EntryGraph({ notes, visible, selectedId, collection, onOpen, onFilter, emptyAction }: {
  notes: ContextNote[]; visible: ContextNote[]; selectedId: string | null; collection: string;
  onOpen: (note: ContextNote) => void; onFilter: (name: string) => void; emptyAction: () => void;
}) {
  const graph = useMemo(() => entryGraph(notes), [notes]);
  const shown = new Set(visible.map((note) => note.id));
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const [size, setSize] = useState({ width: 800, height: 520 });
  const [camera, setCamera] = useState({ zoom: 1, x: 0, y: 0 });
  const [hovered, setHovered] = useState<string | null>(null);
  useEffect(() => {
    if (!viewport.current || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      // The graph stays mounted behind entry tabs; ignore hidden-panel sizes.
      if (entry.contentRect.width && entry.contentRect.height) setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
    });
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);
  const scale = Math.min(size.width / graph.width, size.height / graph.height) * .9 * camera.zoom;
  const changeZoom = (factor: number) => setCamera((previous) => ({ ...previous, zoom: Math.max(.4, Math.min(8, previous.zoom * factor)) }));
  const collections = [...new Set(notes.map(collectionOf))].sort();
  return <section className="entry-graph" aria-label="Entry network">
    <div className="graph-heading"><div><span className="graph-live-dot" /><strong>Knowledge network</strong><span>{visible.length} entries</span></div>
      <div className="graph-controls"><button type="button" aria-label="Zoom out" disabled={camera.zoom <= .4} onClick={() => changeZoom(1 / 1.25)}>−</button>
        <output aria-label="Graph zoom">{Math.round(camera.zoom * 100)}%</output>
        <button type="button" aria-label="Zoom in" disabled={camera.zoom >= 8} onClick={() => changeZoom(1.25)}>+</button>
        <button type="button" className="graph-fit" onClick={() => setCamera({ zoom: 1, x: 0, y: 0 })}>Reset view</button></div></div>
    <div className="graph-viewport" ref={viewport} role="group" aria-label="Graph canvas" aria-describedby="graph-help" onPointerDown={(event) => {
      if (event.button !== 0 || (event.target as Element).closest("button")) return;
      drag.current = { x: event.clientX, y: event.clientY, panX: camera.x, panY: camera.y };
      event.currentTarget.setPointerCapture(event.pointerId);
    }} onPointerMove={(event) => {
      if (drag.current) setCamera((previous) => ({ ...previous, x: drag.current!.panX + event.clientX - drag.current!.x,
        y: drag.current!.panY + event.clientY - drag.current!.y }));
    }} onPointerUp={() => { drag.current = null; }} onPointerCancel={() => { drag.current = null; }}>
      {visible.length ? <div className="graph-world" style={{ width: graph.width, height: graph.height,
        transform: `translate(calc(-50% + ${camera.x}px), calc(-50% + ${camera.y}px)) scale(${scale})` }}>
        <svg className="graph-connections" width={graph.width} height={graph.height} aria-hidden="true">
          {graph.edges.filter((edge) => shown.has(edge.from.note.id) && shown.has(edge.to.note.id)).map((edge) => <line key={edge.key}
            x1={edge.from.x} y1={edge.from.y} x2={edge.to.x} y2={edge.to.y}
            className={hovered === edge.from.note.id || hovered === edge.to.note.id ? "is-highlighted" : ""} />)}
        </svg>
        {graph.nodes.filter((node) => shown.has(node.note.id)).map(({ note, x, y, color }) => <button type="button" key={note.id}
          className={`graph-node${selectedId === note.id ? " is-selected" : ""}`} style={{ left: x, top: y, "--node-color": color } as CSSProperties}
          aria-label={`Open ${note.title}`} title={`${note.title}\n${note.path}`} onClick={() => onOpen(note)}
          onMouseEnter={() => setHovered(note.id)} onMouseLeave={() => setHovered(null)} onFocus={() => setHovered(note.id)} onBlur={() => setHovered(null)}>
          <span className="graph-node-halo"><span className="graph-node-dot" /></span><span className="graph-node-title">{note.title}</span>
          <span className="graph-node-collection">{collectionOf(note)}</span>
        </button>)}
      </div> : <div className="graph-empty"><span aria-hidden="true">◌</span><h3>{notes.length ? "No matching entries" : "Your network starts with a note"}</h3>
        <p>{notes.length ? "Try a different search or collection." : "Add Markdown notes to your vault to populate the graph."}</p>
        <button className="button button-secondary" onClick={emptyAction}>{notes.length ? "Clear filters" : "Add your first entry"}</button></div>}
      <span className="graph-canvas-label" aria-hidden="true">PAGE / CONNECTED CONTEXT</span>
    </div>
    <div className="graph-legend" aria-label="Graph collections"><button type="button" aria-pressed={collection === "All collections"} onClick={() => onFilter("All collections")}>All collections</button>
      {collections.map((name) => <button type="button" key={name} aria-pressed={collection === name} onClick={() => onFilter(name)}>
        <span style={{ background: collectionColor(name) }} />{name}</button>)}</div>
    <p className="graph-help" id="graph-help">Select a node to open an entry tab. Drag the background to pan. Lines connect entries in the same collection.</p>
  </section>;
}
