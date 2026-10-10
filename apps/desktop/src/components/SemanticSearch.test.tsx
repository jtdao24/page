// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Workspace } from "./Workspace";
import { WorkspaceController } from "../workspace/controller";
import { deferred, failure, note, ready, testClient, vault } from "../workspace/testClient";
import type { SearchResponse } from "../core/types";

const a = note(), b = note("33333333-3333-4333-8333-333333333333", "garden text", "garden.md");
const results: SearchResponse = { vault_id: vault.id, model: "test", hits: [{
  chunk_id: "44444444-4444-4444-8444-444444444444", note_id: b.id, relative_path: b.relative_path,
  revision: b.revision, ordinal: 0, text: b.content, start_byte: 0, end_byte: 11,
  start_line: 1, end_line: 1, score: 0.85,
}] };
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
async function click(label: string) {
  const button = [...host.querySelectorAll("button")].find((b) => b.textContent === label || b.getAttribute("aria-label") === label)!;
  expect(button).toBeDefined(); await act(async () => button.click());
}
async function query(value: string) {
  const input = host.querySelector<HTMLInputElement>("#semantic-query")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function setup() {
  const { client, emit } = testClient(); client.noteList.mockResolvedValue([a,b]);
  client.noteRead.mockImplementation(async (_vault, id) => id === b.id ? b : a);
  client.semanticSearch.mockResolvedValue(results);
  const controller = new WorkspaceController(client);
  await act(async () => root.render(<Workspace controller={controller} />));
  await act(async () => { await controller.openVault(vault.root_path); await controller.selectNote(a.id); });
  await click("Semantic search"); await query("baby vegetables");
  return { client, controller, emit };
}
describe("semantic workspace search", () => {
  it("a search that loses ownership during a brief change does not stay loading", async () => {
    const { client, emit } = await setup();
    const pending = deferred<SearchResponse>();
    client.semanticSearch.mockReturnValueOnce(pending.promise);
    await click("Search Notes");
    expect(host.textContent).toContain("Indexing saved notes and searching…");
    await act(async () => emit({ ...ready, state: "failed", error: failure("backend_exited") }));
    await act(async () => emit(ready));
    await act(async () => pending.resolve(results));
    expect(host.textContent).not.toContain("Indexing saved notes and searching…");
    const search = [...host.querySelectorAll("button")].find((b) => b.textContent === "Search Notes")!;
    expect(search.disabled).toBe(false);
  });
  it("searches saved notes and routes result navigation through the dirty guard", async () => {
    const { client, controller } = await setup();
    const doc = controller.getState().document!;
    await act(async () => controller.setDraft(a.id, doc.editorKey, "unsaved draft"));
    await click("Search Notes");
    expect(client.semanticSearch).toHaveBeenCalledWith(vault.id, "baby vegetables", 10);
    expect(host.querySelector(".search-panel")?.textContent).toContain("garden text");
    expect(host.querySelector(".search-panel")?.textContent).toContain("Lines 1–1");
    await act(async () => host.querySelector<HTMLButtonElement>(".search-results button")!.click());
    expect(host.textContent).toContain("Unsaved Changes"); await click("Cancel");
    expect(controller.getState().document?.draft).toBe("unsaved draft");
    await act(async () => host.querySelector<HTMLButtonElement>(".search-results button")!.click());
    await click("Discard"); expect(controller.getState().document?.noteId).toBe(b.id);
  });
  it("ignores closed and previous-generation responses", async () => {
    const { client, emit } = await setup(); const pending = deferred<SearchResponse>();
    client.semanticSearch.mockReturnValueOnce(pending.promise); await click("Search Notes");
    await act(async () => emit({ state: "failed", generation: 1, core_version: null, error: failure("crashed") }));
    await act(async () => pending.resolve(results));
    expect(host.querySelector(".search-results")).toBeNull();
    await click("Close search"); expect(host.querySelector(".search-panel")).toBeNull();
  });
  it("rejects old vault responses and recovers corrupt indexes explicitly", async () => {
    const { client, controller } = await setup(); const old = deferred<SearchResponse>();
    client.semanticSearch.mockReturnValueOnce(old.promise); await click("Search Notes");
    const other = {...vault, id:"55555555-5555-4555-8555-555555555555",root_path:"/tmp/other"};
    client.vaultOpen.mockResolvedValue(other); client.noteList.mockResolvedValue([]);
    await act(async () => { await controller.openVault(other.root_path); });
    await act(async () => old.resolve(results)); expect(host.querySelector(".search-results")).toBeNull();
    client.semanticSearch.mockRejectedValue(failure("index_corrupt")); await click("Search Notes");
    expect(host.querySelector(".search-panel [role=alert]")).not.toBeNull();
    await click("Rebuild Index"); expect(client.semanticIndex).toHaveBeenCalledWith(other.id, true);
    expect(host.querySelector(".search-panel")?.textContent).toContain("Index rebuilt");
  });
  it("invalidates results after saved changes and ignores an unmounted request", async () => {
    const { client, controller } = await setup(); await click("Search Notes");
    const doc = controller.getState().document!;
    await act(async () => { controller.setDraft(a.id,doc.editorKey,"saved change"); await controller.save(); });
    expect(host.querySelector(".search-results")).toBeNull();
    const pending = deferred<SearchResponse>(); client.semanticSearch.mockReturnValueOnce(pending.promise);
    await click("Search Notes"); await click("Close search");
    await act(async () => pending.resolve(results)); expect(host.querySelector(".search-panel")).toBeNull();
  });
});
