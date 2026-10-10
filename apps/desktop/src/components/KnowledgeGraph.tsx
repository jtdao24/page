import cytoscape, { type Core } from "cytoscape";
import { useEffect, useRef } from "react";
import type { GraphData } from "../types";

interface KnowledgeGraphProps {
  data: GraphData;
  activeId: string | null;
  onOpenNote: (noteId: string) => void;
}

export default function KnowledgeGraph({ data, activeId, onOpenNote }: KnowledgeGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onOpenNoteRef = useRef(onOpenNote);
  onOpenNoteRef.current = onOpenNote;

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...data.nodes.map((node) => ({
          data: { id: node.id, label: node.title },
        })),
        ...data.edges.map((edge) => ({
          data: {
            id: `${edge.source}->${edge.target}`,
            source: edge.source,
            target: edge.target,
          },
        })),
      ],
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: "#171717",
            "background-color": "#e5e5e5",
            "border-color": "#a3a3a3",
            "border-width": 1,
            "font-size": 11,
            "text-wrap": "wrap",
            "text-max-width": "80px",
            width: 22,
            height: 22,
          },
        },
        {
          selector: "node:selected",
          style: {
            "background-color": "#171717",
            color: "#171717",
            "border-color": "#171717",
            "font-weight": "bold",
          },
        },
        {
          selector: "edge",
          style: {
            width: 1.5,
            "line-color": "#a3a3a3",
            "target-arrow-color": "#a3a3a3",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "arrow-scale": 0.8,
          },
        },
      ],
      layout: {
        name: "cose",
        animate: false,
        padding: 24,
        nodeRepulsion: 6000,
      },
      minZoom: 0.3,
      maxZoom: 2.5,
      wheelSensitivity: 0.3,
    });

    const onTap = (event: cytoscape.EventObject) => {
      const id = event.target.id();
      if (id) {
        onOpenNoteRef.current(id);
      }
    };
    cy.on("tap", "node", onTap);
    cyRef.current = cy;

    return () => {
      cy.off("tap", "node", onTap);
      cy.destroy();
      cyRef.current = null;
    };
  }, [data]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    cy.nodes().unselect();
    if (activeId && cy.getElementById(activeId).length > 0) {
      cy.getElementById(activeId).select();
    }
  }, [activeId, data]);

  return (
    <section className="flex h-64 shrink-0 flex-col border-t border-neutral-200 bg-neutral-50">
      <div className="border-b border-neutral-200 px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
          Knowledge graph
        </h2>
      </div>
      {data.nodes.length === 0 ? (
        <p className="px-3 py-3 text-sm text-neutral-500">Create a note to see it on the graph.</p>
      ) : (
        <div ref={containerRef} className="min-h-0 flex-1" />
      )}
    </section>
  );
}
