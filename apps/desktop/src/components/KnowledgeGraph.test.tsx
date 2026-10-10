// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { Core } from "cytoscape";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Workspace } from "./Workspace";
import { WorkspaceController } from "../workspace/controller";
import { testClient, note, vault, deferred } from "../workspace/testClient";
import type { GraphResponse } from "../core/types";

const registry = vi.hoisted(() => ({ instances: [] as Core[] }));
// jsdom has no canvas renderer. Keep real Cytoscape topology/events; replace
// only the canvas boundary with its supported headless mode.
vi.mock("../workspace/graph", async (original) => {
  const module = await original<typeof import("../workspace/graph")>();
  return { ...module, createKnowledgeGraph: (_container: HTMLElement, graph: GraphResponse, onOpen: (id: string) => void) => {
    const cy = module.createKnowledgeGraph(null, graph, onOpen); registry.instances.push(cy); return cy;
  } };
});
const a = note(), b = note("33333333-3333-4333-8333-333333333333", "B", "b.md");
const graph: GraphResponse = { vault_id: vault.id, nodes: [a,b].map((n) => ({id:n.id, relative_path:n.relative_path})), links: [
  {source_note_id:a.id, target_note_id:b.id, target_reference:"b",alias:"B",line:1,unresolved_reason:null},
  {source_note_id:a.id, target_note_id:null,target_reference:"Missing",alias:null,line:2,unresolved_reason:"missing"},
] };
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis,{ IS_REACT_ACT_ENVIRONMENT: true });
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  registry.instances = []; host=document.createElement("div"); document.body.append(host); root=createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
async function click(label: string) {
  const button=[...host.querySelectorAll("button")].find((b)=>b.textContent===label || b.getAttribute("aria-label")===label)!;
  expect(button).toBeDefined(); await act(async()=> { button.click(); if (label === "Knowledge graph") await import("./KnowledgeGraph"); });
}
async function setup() {
  const {client}=testClient(); client.noteList.mockResolvedValue([a,b]);client.noteRead.mockImplementation(async(_vault,id)=>id===b.id?b:a);
  client.graphRead.mockResolvedValue(graph);
  const controller=new WorkspaceController(client);
  await act(async()=>root.render(<Workspace controller={controller}/>));
  await act(async()=> {await controller.openVault(vault.root_path);await controller.selectNote(a.id);});
  return {client,controller};
}
describe("graph workspace",()=> {
  it("navigates real graph taps and backlinks through the dirty guard",async()=> {
    const {controller}=await setup(); await click("Knowledge graph");
    const initialGraph = registry.instances.at(-1)!;
    expect(host.textContent).toContain("Missing · missing");
    const draft=controller.getState().document!;
    await act(async()=>controller.setDraft(a.id,draft.editorKey,"dirty"));
    await act(async()=>registry.instances.at(-1)!.getElementById(b.id).emit("tap"));
    expect(host.textContent).toContain("Unsaved Changes");await click("Cancel");
    expect(controller.getState().document?.draft).toBe("dirty");
    await act(async()=>registry.instances.at(-1)!.getElementById(b.id).emit("tap"));await click("Discard");
    expect(controller.getState().document?.noteId).toBe(b.id);
    expect(registry.instances.at(-1)).toBe(initialGraph);
    const panel=host.querySelector('[aria-label="Knowledge graph"] aside') ?? host.querySelector(".knowledge-panel")!;
    expect(panel.textContent).toContain("Backlinks");
    const backlink=[...panel.querySelectorAll("button")].filter((button)=>button.textContent==="a.md").at(-1)!;
    await act(async()=>backlink.click());expect(controller.getState().document?.noteId).toBe(a.id);
    await click("Close graph");expect(registry.instances.every((cy)=>cy.destroyed())).toBe(true);
  });
  it("refreshes after saves and reports graph errors with retry",async()=> {
    const {client,controller}=await setup();await click("Knowledge graph");
    const before=client.graphRead.mock.calls.length;const doc=controller.getState().document!;
    client.graphRead.mockRejectedValue({kind:"api",status:500,code:"storage_error",message:"Graph could not load.",details:null});
    await act(async()=> {controller.setDraft(a.id,doc.editorKey,"changed");await controller.save();});
    expect(client.graphRead.mock.calls.length).toBeGreaterThan(before);
    expect(host.querySelector(".knowledge-panel [role=alert]")).not.toBeNull();
    client.graphRead.mockResolvedValue(graph);
    await click("Retry Graph");expect(host.textContent).toContain("2 notes · 2 links");
  });
  it("ignores an old vault graph after switching vaults", async () => {
    const {client,controller}=await setup();const old=deferred<GraphResponse>();client.graphRead.mockReturnValueOnce(old.promise);
    await click("Knowledge graph");
    const other={...vault,id:"44444444-4444-4444-8444-444444444444",root_path:"/tmp/other",name:"Other"};
    client.vaultOpen.mockResolvedValue(other);client.noteList.mockResolvedValue([]);
    client.graphRead.mockResolvedValue({vault_id:other.id,nodes:[],links:[]});
    await act(async()=> {await controller.openVault(other.root_path);});
    await act(async()=>old.resolve(graph));
    expect(host.querySelector(".knowledge-panel")?.textContent).toContain("0 notes · 0 links");
    expect(host.querySelector(".knowledge-panel")?.textContent).not.toContain("Missing");
  });
  it("ignores responses after closing the graph",async()=> {
    const {client}=await setup();const pending=deferred<GraphResponse>();client.graphRead.mockReturnValueOnce(pending.promise);
    await click("Knowledge graph");expect(host.textContent).toContain("Loading graph…");await click("Close graph");
    await act(async()=>pending.resolve(graph));expect(host.querySelector(".knowledge-panel")).toBeNull();
    expect(registry.instances).toHaveLength(0);
  });
});
