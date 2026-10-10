import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import type { GraphResponse } from "../core/types";

/** Unresolved nodes are scoped by source and exact reference, never note UUIDs. */
export function graphElements(graph: GraphResponse): ElementDefinition[] {
  const elements: ElementDefinition[] = graph.nodes.map((node) => ({
    data: { id: node.id, noteId: node.id, label: node.relative_path.replace(/\.md$/, ""), unresolved: false },
  }));
  const ghosts = new Set<string>();
  graph.links.forEach((link, index) => {
    const target = link.target_note_id ?? `unresolved:${JSON.stringify([link.source_note_id, link.target_reference])}`;
    if (link.target_note_id === null && !ghosts.has(target)) {
      ghosts.add(target);
      elements.push({ data: { id: target, label: link.target_reference, unresolved: true } });
    }
    elements.push({ data: { id: `edge:${index}`, source: link.source_note_id, target } });
  });
  return elements;
}

/** Real Cytoscape is also used headlessly by behavior tests. */
export function createKnowledgeGraph(container: HTMLElement | null, graph: GraphResponse, onOpen: (id: string) => void): Core {
  const cy = cytoscape({
    ...(container ? { container } : { headless: true }),
    elements: graphElements(graph),
    layout: { name: "circle", padding: 28, animate: false },
    minZoom: .2, maxZoom: 3,
    style: [
      { selector: "node", style: { "background-color": "#b39af6", label: "data(label)", color: "#ccc4d7", "font-size": 11,
        width: 18, height: 18, "text-valign": "bottom", "text-margin-y": 8, "text-wrap": "wrap", "text-max-width": "120px" } },
      { selector: "node[?unresolved]", style: { "background-color": "#77716b", "border-width": 2, "border-color": "#c4a876", "border-style": "dashed" } },
      { selector: "node:selected", style: { "background-color": "#e3d0ff", "border-color": "#e3d0ff", "border-width": 3 } },
      { selector: "edge", style: { width: 1, "line-color": "#665979", "target-arrow-color": "#665979", "target-arrow-shape": "triangle", "curve-style": "bezier" } },
    ],
  });
  cy.on("tap", "node", (event) => {
    const noteId: unknown = event.target.data("noteId");
    if (typeof noteId === "string") onOpen(noteId);
  });
  return cy;
}
