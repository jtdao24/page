// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Workspace } from "./Workspace";
import { WorkspaceController } from "../workspace/controller";
import { deferred, failure, note, testClient, vault } from "../workspace/testClient";
import type { AskResponse, SourceSummaryResponse } from "../core/types";

const a = note();
const pdf: SourceSummaryResponse = { id: "55555555-5555-4555-8555-555555555555", relative_path: "papers/study.pdf", kind: "pdf", size_bytes: 900 };
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
async function setup() {
  const { client } = testClient();
  client.noteList.mockResolvedValue([a]);
  client.sourceList.mockResolvedValue([pdf]);
  client.sourceRead.mockResolvedValue({ ...pdf, vault_id: vault.id, revision: "c".repeat(64),
    content: "[Page 1]\nline two\nespresso uses 18 g\nline four\n" });
  const controller = new WorkspaceController(client);
  await act(async () => root.render(<Workspace controller={controller} />));
  await act(async () => { await controller.openVault(vault.root_path); await controller.selectNote(a.id); });
  return { client, controller };
}

describe("read-only sources", () => {
  it("lists sources in Files and opens them read-only without losing the note draft", async () => {
    const { client, controller } = await setup();
    expect(client.sourceList).toHaveBeenCalledWith(vault.id);
    const row = [...host.querySelectorAll<HTMLButtonElement>(".source-row")].find((b) => b.textContent === "study.pdf")!;
    const doc = controller.getState().document!;
    await act(async () => controller.setDraft(a.id, doc.editorKey, "unsaved draft"));
    await act(async () => row.click());
    expect(client.sourceRead).toHaveBeenCalledWith(vault.id, pdf.id);
    const viewer = host.querySelector(".source-viewer")!;
    expect(viewer.textContent).toContain("PDF · read-only");
    expect(viewer.querySelector(".source-text")?.textContent).toBe("[Page 1]\nline two\nespresso uses 18 g\nline four");
    expect(viewer.querySelector(".source-gutter")?.textContent).toBe("1\n2\n3\n4");
    expect(host.textContent).not.toContain("Unsaved Changes");
    await click("Close source");
    expect(host.querySelector(".source-viewer")).toBeNull();
    expect(controller.getState().document?.draft).toBe("unsaved draft");
  });
  it("opens a cited PDF at the cited lines from the ask card", async () => {
    const { client } = await setup();
    const answer: AskResponse = { vault_id: vault.id, model: "m", answer: "18 g [1].", answered_by_model: true, finish_reason: "STOP",
      cited: [1], sources: [{ number: 1, note_id: pdf.id, relative_path: pdf.relative_path, kind: "pdf", start_line: 3, end_line: 3,
        text: "espresso uses 18 g", excerpt: false }],
      usage: { context_tokens: 9, budget: 1500, counter: "utf8-bytes/3", input_tokens: 20, output_tokens: 3 } };
    client.askQuestion.mockResolvedValue(answer);
    const input = host.querySelector<HTMLTextAreaElement>("#ask-question")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, "how much?");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click("Ask");
    await act(async () => host.querySelector<HTMLButtonElement>(".ask-answer .citation")!.click());
    const highlight = host.querySelector<HTMLElement>(".source-highlight")!;
    expect(highlight.style.top).toBe("42px");
    expect(client.noteRead).toHaveBeenCalledTimes(1);
  });
  it("saves a website as a note and opens it", async () => {
    const { client, controller } = await setup();
    const pending = deferred<ReturnType<typeof note>>();
    client.webPageSave.mockReturnValueOnce(pending.promise);
    await click("Add website");
    const field = host.querySelector<HTMLInputElement>("#web-page-url")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, " https://example.com/espresso ");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click("Save Page");
    expect(client.webPageSave).toHaveBeenCalledWith(vault.id, "https://example.com/espresso");
    expect(host.textContent).toContain("Downloading and saving…");
    const saved = note("77777777-7777-4777-8777-777777777777", "# Espresso", "web/example.com/espresso.md");
    await act(async () => pending.resolve(saved));
    expect(controller.getState().document?.noteId).toBe(saved.id);
    expect(host.querySelector("#web-page-url")).toBeNull();
    expect(host.textContent).toContain("Saved web/example.com/espresso.md.");
  });
  it("keeps the dialog open with the error when a page can't be saved", async () => {
    const { client } = await setup();
    client.webPageSave.mockRejectedValueOnce({ ...failure("invalid_url"), message: "Enter a full http:// or https:// address." });
    await click("Add website");
    const field = host.querySelector<HTMLInputElement>("#web-page-url")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, "http://localhost/admin");
      field.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await click("Save Page");
    expect(host.querySelector(".web-page-form [role=alert]")?.textContent).toContain("Enter a full http://");
    expect(button("Save Page")?.disabled).toBe(false);
  });
});
