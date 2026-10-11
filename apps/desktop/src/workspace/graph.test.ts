import { describe, expect, it } from "vitest";
import { createKnowledgeGraph, folderColor, graphElements } from "./graph";
import type { GraphResponse } from "../core/types";

export const linkedGraph: GraphResponse = {
  vault_id: "vault", nodes: [{ id: "a", relative_path: "a.md" }, { id: "b", relative_path: "nested/b.md" }],
  links: [
    { source_note_id: "a", target_note_id: "b", target_reference: "b", line: 1, alias: null, unresolved_reason: null },
    { source_note_id: "a", target_note_id: null, target_reference: "Missing", line: 2, alias: null, unresolved_reason: "missing" },
  ],
};

describe("Cytoscape knowledge graph", () => {
  it("renders real directed topology and opens only canonical note nodes", () => {
    const opened: string[] = [];
    const cy = createKnowledgeGraph(null, linkedGraph, (id) => opened.push(id));
    expect(cy.nodes()).toHaveLength(3); expect(cy.edges()).toHaveLength(2);
    expect(cy.getElementById("a").outgoers("node").map((n) => n.id())).toContain("b");
    expect(cy.getElementById("b").incomers("node").map((n) => n.id())).toEqual(["a"]);
    cy.getElementById("b").emit("tap");
    cy.nodes().filter((node) => node.data("unresolved") === true).emit("tap");
    expect(opened).toEqual(["b"]);
    cy.destroy(); expect(cy.destroyed()).toBe(true);
  });
  it("retains repeated edges and shares only identical unresolved references from one source", () => {
    const graph = { ...linkedGraph, links: [...linkedGraph.links, linkedGraph.links[1]] };
    const elements = graphElements(graph);
    expect(elements).toHaveLength(6);
    expect(new Set(elements.map((e) => e.data.id)).size).toBe(6);
    const cy = createKnowledgeGraph(null, graph, () => {});
    expect(cy.edges()).toHaveLength(3); cy.destroy();
  });
  it("colors notes by top-level folder, sizes them by links and labels them by file name", () => {
    expect(folderColor("a.md")).toBe(folderColor("b.md"));
    expect(folderColor("garden/x.md")).toBe(folderColor("garden/deep/y.md"));
    expect(folderColor("garden/x.md")).not.toBe(folderColor("a.md"));
    const cy = createKnowledgeGraph(null, linkedGraph, () => {});
    expect(cy.getElementById("a").data("degree")).toBe(2);
    expect(cy.getElementById("b").data("degree")).toBe(1);
    expect(cy.getElementById("b").data("label")).toBe("b");
    expect(cy.getElementById("b").data("path")).toBe("nested/b.md");
    cy.destroy();
  });
  it("highlights a hovered note's neighborhood and fades the rest", () => {
    const graph = { ...linkedGraph, nodes: [...linkedGraph.nodes, { id: "c", relative_path: "c.md" }] };
    const cy = createKnowledgeGraph(null, graph, () => {});
    cy.getElementById("b").emit("mouseover");
    expect(cy.getElementById("a").hasClass("focused")).toBe(true);
    expect(cy.getElementById("c").hasClass("faded")).toBe(true);
    cy.getElementById("b").emit("mouseout");
    expect(cy.elements(".faded, .focused")).toHaveLength(0);
    cy.destroy();
  });
});
