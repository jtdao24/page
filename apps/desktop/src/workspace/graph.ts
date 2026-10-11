import cytoscape, { type Core, type ElementDefinition, type LayoutOptions } from "cytoscape";
import type { GraphResponse } from "../core/types";

/** Soft colors that read well on the dark canvas; each top-level folder gets one. */
const PALETTE = ["#7fa6e3", "#7cc4d8", "#e7a77c", "#8fcf9b", "#e88fb4", "#d9c36f", "#c9a0dc", "#77d1bd"];
const ROOT_COLOR = "#9fbbe8";
const UNRESOLVED_COLOR = "#6f6a64";

export function folderColor(relativePath: string): string {
  const slash = relativePath.indexOf("/");
  if (slash < 0) return ROOT_COLOR;
  const folder = relativePath.slice(0, slash);
  let hash = 0;
  for (const char of folder) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return PALETTE[hash % PALETTE.length];
}

/** Unresolved nodes are scoped by source and exact reference, never note UUIDs. */
export function graphElements(graph: GraphResponse): ElementDefinition[] {
  const degree = new Map<string, number>();
  const bump = (id: string) => degree.set(id, (degree.get(id) ?? 0) + 1);
  const elements: ElementDefinition[] = graph.nodes.map((node) => ({
    data: {
      id: node.id, noteId: node.id, path: node.relative_path, unresolved: false, color: folderColor(node.relative_path),
      label: node.relative_path.replace(/\.md$/, "").split("/").at(-1),
    },
  }));
  const ghosts = new Set<string>();
  graph.links.forEach((link, index) => {
    const target = link.target_note_id ?? `unresolved:${JSON.stringify([link.source_note_id, link.target_reference])}`;
    if (link.target_note_id === null && !ghosts.has(target)) {
      ghosts.add(target);
      elements.push({ data: { id: target, label: link.target_reference, unresolved: true, color: UNRESOLVED_COLOR } });
    }
    bump(link.source_note_id);
    bump(target);
    elements.push({ data: { id: `edge:${index}`, source: link.source_note_id, target } });
  });
  for (const element of elements) {
    if (element.data.source === undefined) element.data.degree = degree.get(element.data.id as string) ?? 0;
  }
  return elements;
}

/**
 * Force-directed layouts cost roughly n² per iteration, so large vaults get
 * cheaper layouts: an animated force layout for small graphs, a shorter
 * unanimated one for medium graphs, and rings by link count for big ones.
 */
export function layoutFor(nodeCount: number, animate: boolean): LayoutOptions {
  if (nodeCount <= 1) return { name: "circle", padding: 40, animate: false };
  if (nodeCount <= 400) {
    return { name: "cose", animate, animationDuration: 700, animationEasing: "ease-out", padding: 48, randomize: true, fit: true,
      nodeRepulsion: () => 14000, idealEdgeLength: () => 80, edgeElasticity: () => 120, gravity: 0.9, numIter: 1500, componentSpacing: 80 };
  }
  if (nodeCount <= 1500) {
    return { name: "cose", animate: false, padding: 48, randomize: true, fit: true, nodeRepulsion: () => 14000,
      idealEdgeLength: () => 80, gravity: 1, numIter: 300, componentSpacing: 60 };
  }
  return { name: "concentric", animate: false, padding: 40, fit: true, minNodeSpacing: 6,
    concentric: (node) => node.degree(false), levelWidth: () => 2 };
}

/** Real Cytoscape is also used headlessly by behavior tests. */
export function createKnowledgeGraph(container: HTMLElement | null, graph: GraphResponse, onOpen: (id: string) => void): Core {
  const animate = container !== null && !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const cy = cytoscape({
    ...(container ? { container } : { headless: true }),
    elements: graphElements(graph),
    layout: layoutFor(graph.nodes.length, animate),
    // Big graphs pan and zoom from a cached image and hide edges while moving.
    ...(graph.nodes.length > 400 ? { textureOnViewport: true, hideEdgesOnViewport: true } : {}),
    minZoom: .15, maxZoom: 3, wheelSensitivity: .3,
    style: [
      { selector: "node", style: {
        "background-color": "data(color)", width: "mapData(degree, 0, 10, 20, 46)", height: "mapData(degree, 0, 10, 20, 46)",
        label: "data(label)", color: "#d4dae4", "font-size": 12, "font-weight": 500, "text-valign": "bottom", "text-margin-y": 7,
        "text-wrap": "ellipsis", "text-max-width": "130px", "text-outline-color": "#1b1b1d", "text-outline-width": 2.5,
        "min-zoomed-font-size": 7, "border-width": 0, "transition-property": "opacity, border-width, background-color",
        "transition-duration": 180,
      } },
      { selector: "node[?unresolved]", style: { "border-width": 1.5, "border-color": "#c4a876", "border-style": "dashed",
        color: "#a59f97", "font-style": "italic" } },
      { selector: "node:selected", style: { "border-width": 3, "border-color": "#eaf1fb", "underlay-color": "#7fa6e3",
        "underlay-opacity": .35, "underlay-padding": 9, "underlay-shape": "ellipse", "font-weight": 700, color: "#fff" } },
      { selector: "edge", style: { width: 1.4, "line-color": "#4c5870", "target-arrow-color": "#4c5870", "target-arrow-shape": "triangle",
        "arrow-scale": .8, "curve-style": "bezier", opacity: .75, "transition-property": "opacity, line-color, width", "transition-duration": 180 } },
      { selector: ".faded", style: { opacity: .14 } },
      { selector: "node.focused", style: { "border-width": 2.5, "border-color": "#ffffff", color: "#fff" } },
      { selector: "edge.focused", style: { "line-color": "#7fa6e3", "target-arrow-color": "#7fa6e3", width: 2, opacity: 1 } },
    ],
  });
  cy.on("tap", "node", (event) => {
    const noteId: unknown = event.target.data("noteId");
    if (typeof noteId === "string") onOpen(noteId);
  });
  // Hovering a note highlights it and its direct neighbors.
  cy.on("mouseover", "node", (event) => {
    const neighborhood = event.target.closedNeighborhood();
    cy.elements().not(neighborhood).addClass("faded");
    neighborhood.addClass("focused");
    if (container) container.style.cursor = event.target.data("noteId") ? "pointer" : "default";
  });
  cy.on("mouseout", "node", () => {
    cy.elements().removeClass("faded focused");
    if (container) container.style.cursor = "";
  });
  return cy;
}
