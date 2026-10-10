// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Workspace } from "./Workspace";
import { WorkspaceController } from "../workspace/controller";
import { deferred, failure, note, ready, testClient, vault } from "../workspace/testClient";
import type { AskResponse } from "../core/types";

const a = note(), b = note("33333333-3333-4333-8333-333333333333", "Water tomatoes at dawn.", "garden.md");
const answer: AskResponse = {
  vault_id: vault.id, model: "gemini-test", answer: "Water them at dawn [1].", answered_by_model: true,
  finish_reason: "STOP", cited: [1],
  sources: [{ number: 1, note_id: b.id, relative_path: b.relative_path, start_line: 1, end_line: 1,
    text: b.content, excerpt: false }],
  usage: { context_tokens: 12, budget: 1500, counter: "utf8-bytes/3", input_tokens: 140, output_tokens: 9 },
};
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
function button(label: string) {
  return [...host.querySelectorAll("button")].find((b) => b.textContent === label || b.getAttribute("aria-label") === label);
}
async function click(label: string) {
  const found = button(label); expect(found).toBeDefined(); await act(async () => found!.click());
}
async function type(value: string) {
  const input = host.querySelector<HTMLTextAreaElement>("#ask-question")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function setup() {
  const { client, emit } = testClient(); client.noteList.mockResolvedValue([a, b]);
  client.noteRead.mockImplementation(async (_vault, id) => id === b.id ? b : a);
  client.askQuestion.mockResolvedValue(answer);
  const controller = new WorkspaceController(client);
  await act(async () => root.render(<Workspace controller={controller} />));
  await act(async () => { await controller.openVault(vault.root_path); await controller.selectNote(a.id); });
  await click("Ask your notes"); await type("  when should I water?  ");
  return { client, controller, emit };
}
describe("ask panel", () => {
  it("asks with the chosen budget and shows the answer, usage and sources", async () => {
    const { client } = await setup();
    expect(button("Ask")!.disabled).toBe(false);
    const select = host.querySelector<HTMLSelectElement>("#ask-budget")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(select, "4000");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await click("Ask");
    expect(client.askQuestion).toHaveBeenCalledWith(vault.id, "when should I water?", 4000);
    const panel = host.querySelector(".ask-panel")!.textContent!;
    expect(panel).toContain("Water them at dawn");
    expect(panel).toContain("Context 12 of 1,500 tokens · gemini-test: 140 in, 9 out");
    expect(panel).toContain("garden.md");
    expect(panel).toContain("cited");
    expect(panel).toContain("not your whole vault");
  });
  it("routes citation navigation through the dirty guard", async () => {
    const { controller } = await setup();
    await click("Ask");
    const doc = controller.getState().document!;
    await act(async () => controller.setDraft(a.id, doc.editorKey, "unsaved draft"));
    await act(async () => host.querySelector<HTMLButtonElement>(".ask-answer .citation")!.click());
    expect(host.textContent).toContain("Unsaved Changes"); await click("Discard");
    expect(controller.getState().document?.noteId).toBe(b.id);
  });
  it("says when no sources were found and Gemini was not called", async () => {
    const { client } = await setup();
    client.askQuestion.mockResolvedValueOnce({ ...answer, answer: "Nothing relevant.", answered_by_model: false,
      finish_reason: "NO_SOURCES", sources: [], cited: [], usage: { ...answer.usage, context_tokens: 0, input_tokens: 0, output_tokens: 0 } });
    await click("Ask");
    expect(host.textContent).toContain("Gemini was not called");
    expect(host.querySelector(".ask-sources")).toBeNull();
  });
  it("explains a missing API key and offers retry for other errors", async () => {
    const { client } = await setup();
    client.askQuestion.mockRejectedValueOnce(failure("llm_not_configured"));
    await click("Ask");
    expect(host.querySelector(".ask-panel [role=alert]")?.textContent).toContain("GEMINI_API_KEY");
    expect(button("Try Again")).toBeUndefined();
    client.askQuestion.mockRejectedValueOnce(failure("llm_rate_limited"));
    await click("Ask");
    expect(button("Try Again")).toBeDefined();
    await click("Try Again");
    expect(host.textContent).toContain("Water them at dawn");
  });
  it("ignores answers from a previous Core process or a closed panel", async () => {
    const { client, emit } = await setup();
    const pending = deferred<AskResponse>(); client.askQuestion.mockReturnValueOnce(pending.promise);
    await click("Ask");
    expect(host.textContent).toContain("asking Gemini");
    await act(async () => emit({ ...ready, state: "failed", error: failure("backend_exited") }));
    await act(async () => emit(ready));
    await act(async () => pending.resolve(answer));
    expect(host.querySelector(".ask-answer")).toBeNull();
    expect(host.textContent).not.toContain("asking Gemini");
    const late = deferred<AskResponse>(); client.askQuestion.mockReturnValueOnce(late.promise);
    await click("Ask"); await click("Close ask");
    await act(async () => late.resolve(answer));
    expect(host.querySelector(".ask-panel")).toBeNull();
  });
  it("is exclusive with semantic search", async () => {
    await setup();
    await click("Semantic search");
    expect(host.querySelector(".ask-panel")).toBeNull();
    expect(host.querySelector(".search-panel")).not.toBeNull();
  });
});
