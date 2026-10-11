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
    text: b.content, excerpt: false, kind: "note" }],
  usage: { context_tokens: 12, budget: 1500, counter: "utf8-bytes/3", input_tokens: 140, output_tokens: 9, vault_tokens: 18400 },
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
  await type("  when should I water?  ");
  return { client, controller, emit };
}
describe("floating ask box", () => {
  it("asks with the chosen budget and shows the answer, usage and sources in a card", async () => {
    const { client } = await setup();
    expect(host.querySelector(".ask-card")).toBeNull();
    const select = host.querySelector<HTMLSelectElement>("#ask-budget")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(select, "4000");
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await click("Ask");
    expect(client.askQuestion).toHaveBeenCalledWith(vault.id, "when should I water?", 4000);
    const card = host.querySelector(".ask-card")!.textContent!;
    expect(card).toContain("when should I water?");
    expect(card).toContain("Water them at dawn");
    expect(card).toContain("Context 12 of 1,500 tokens · gemini-test: 140 in, 9 out");
    const savings = host.querySelector(".ask-savings")!;
    expect(savings.textContent).toBe("12 sent vs ~18.4K for the whole vault99% less");
    expect(card).toContain("garden.md");
    expect(card).toContain("not your whole vault");
    expect(host.querySelector<HTMLTextAreaElement>("#ask-question")!.value).toBe("");
  });
  it("submits with Enter, keeps follow-ups in one thread and closes with Escape", async () => {
    const { client } = await setup();
    const input = host.querySelector<HTMLTextAreaElement>("#ask-question")!;
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true })));
    expect(client.askQuestion).not.toHaveBeenCalled();
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    await type("and in winter?");
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })));
    expect(client.askQuestion).toHaveBeenCalledTimes(2);
    expect(host.querySelectorAll(".ask-exchange")).toHaveLength(2);
    await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(host.querySelector(".ask-card")).toBeNull();
    await act(async () => input.dispatchEvent(new FocusEvent("focusin", { bubbles: true })));
    expect(host.querySelectorAll(".ask-exchange")).toHaveLength(2);
    await click("New conversation");
    expect(host.querySelectorAll(".ask-exchange")).toHaveLength(0);
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
    expect(host.querySelector(".ask-savings")).toBeNull();
    expect(host.querySelector(".ask-sources")).toBeNull();
  });
  it("explains a missing API key and offers retry for other errors", async () => {
    const { client } = await setup();
    client.askQuestion.mockRejectedValueOnce(failure("llm_not_configured"));
    await click("Ask");
    expect(host.querySelector(".ask-card [role=alert]")?.textContent).toContain("Add one above");
    expect(host.querySelector("#gemini-key")).not.toBeNull();
    expect(button("Try Again")).toBeUndefined();
    client.askQuestion.mockRejectedValueOnce(failure("llm_rate_limited"));
    await type("when should I water?");
    await click("Ask");
    expect(button("Try Again")).toBeDefined();
    await click("Try Again");
    expect(host.textContent).toContain("Water them at dawn");
  });
  it("drops answers from a previous Core process and starts over in another vault", async () => {
    const { client, controller, emit } = await setup();
    const pending = deferred<AskResponse>(); client.askQuestion.mockReturnValueOnce(pending.promise);
    await click("Ask");
    expect(host.textContent).toContain("asking Gemini");
    await act(async () => emit({ ...ready, state: "failed", error: failure("backend_exited") }));
    await act(async () => emit(ready));
    await act(async () => pending.resolve(answer));
    expect(host.querySelector(".ask-answer")).toBeNull();
    expect(host.textContent).not.toContain("asking Gemini");
    expect(host.textContent).toContain("interrupted");
    const other = { ...vault, id: "55555555-5555-4555-8555-555555555555", root_path: "/tmp/other" };
    client.vaultOpen.mockResolvedValue(other); client.noteList.mockResolvedValue([]);
    await act(async () => { await controller.openVault(other.root_path); });
    expect(host.querySelectorAll(".ask-exchange")).toHaveLength(0);
  });
  it("is focused by Cmd/Ctrl+K and the sidebar's Ask item", async () => {
    await setup();
    const input = host.querySelector<HTMLTextAreaElement>("#ask-question")!;
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true })));
    expect(document.activeElement).toBe(input);
    input.blur();
    await click("Ask your notes");
    expect(document.activeElement).toBe(input);
  });
  it("saves a key to the credential store, restarts Core and clears the field", async () => {
    const { client } = await setup();
    await click("Gemini API key");
    expect(host.textContent).toContain("No Gemini API key is set");
    expect(button("Remove Key")).toBeUndefined();
    const input = host.querySelector<HTMLInputElement>("#gemini-key")!;
    expect(input.type).toBe("password");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "AIza-secret");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    client.geminiKeyStatus.mockResolvedValue({ stored: true, from_environment: false });
    await click("Save Key");
    expect(client.geminiKeySave).toHaveBeenCalledWith("AIza-secret");
    expect(client.backendRestart).toHaveBeenCalledTimes(1);
    expect(input.value).toBe("");
    expect(host.textContent).toContain("Key saved. Page Core restarted to use it.");
    expect(host.textContent).toContain("saved in your system keychain");
    client.geminiKeyStatus.mockResolvedValue({ stored: false, from_environment: true });
    await click("Remove Key");
    expect(client.geminiKeyClear).toHaveBeenCalledTimes(1);
    expect(client.backendRestart).toHaveBeenCalledTimes(2);
    expect(host.textContent).toContain("Using GEMINI_API_KEY from the environment");
  });
  it("shows credential store failures and keeps the typed key", async () => {
    const { client } = await setup();
    await click("Gemini API key");
    const input = host.querySelector<HTMLInputElement>("#gemini-key")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "bad key");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    client.geminiKeySave.mockRejectedValueOnce({ kind: "preferences", status: null, code: "invalid_api_key",
      message: "Paste the API key exactly as Google AI Studio shows it.", details: null });
    await click("Save Key");
    expect(host.querySelector(".ask-key [role=alert]")?.textContent).toContain("Paste the API key exactly");
    expect(client.backendRestart).not.toHaveBeenCalled();
    expect(input.value).toBe("bad key");
  });
  it("retries a failed question without erasing what's being typed", async () => {
    const { client } = await setup();
    client.askQuestion.mockRejectedValueOnce(failure("llm_rate_limited"));
    await click("Ask");
    await type("a different draft");
    await click("Try Again");
    expect(client.askQuestion).toHaveBeenLastCalledWith(vault.id, "when should I water?", 1500);
    expect(host.querySelector<HTMLTextAreaElement>("#ask-question")!.value).toBe("a different draft");
  });
  it("is ready again as soon as Core recovers, even if the old request never returns", async () => {
    const { client, emit } = await setup();
    client.askQuestion.mockReturnValueOnce(new Promise(() => {}));
    await click("Ask");
    await act(async () => emit({ ...ready, state: "failed", error: failure("backend_exited") }));
    await act(async () => emit(ready));
    expect(host.textContent).not.toContain("asking Gemini");
    await type("next question");
    expect(button("Ask")!.disabled).toBe(false);
  });
});

