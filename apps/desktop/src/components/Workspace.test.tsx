// @vitest-environment jsdom
import { act, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { EditorView } from "@codemirror/view";
import { undo } from "@codemirror/commands";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { WorkspaceController, isDirty } from "../workspace/controller";
import { deferred, failure, note, testClient, vault } from "../workspace/testClient";
import { Workspace } from "./Workspace";
import type { NoteResponse } from "../core/types";

let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  // jsdom has no layout. CodeMirror needs these methods; tests assert content
  // and selection, never pixel geometry.
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
async function mount(controller: WorkspaceController) {
  await act(async () => root.render(<StrictMode><Workspace controller={controller} /></StrictMode>));
}
function button(text: string, scope: ParentNode = host): HTMLButtonElement {
  const result = [...scope.querySelectorAll("button")].find((item) => item.textContent === text || item.getAttribute("aria-label") === text);
  if (!result) throw new Error(`Missing button: ${text}`);
  return result;
}
async function click(text: string, scope: ParentNode = host) { await act(async () => button(text, scope).click()); }
function editor(): EditorView {
  const element = host.querySelector(".cm-editor");
  const view = element && EditorView.findFromDOM(element as HTMLElement);
  if (!view) throw new Error("No actual CodeMirror view");
  return view;
}
async function setup(content = "original") {
  const { client } = testClient();
  client.noteRead.mockResolvedValue(note(undefined, content));
  const controller = new WorkspaceController(client);
  await mount(controller);
  await act(async () => { await controller.openVault(vault.root_path); await controller.selectNote(note().id); });
  return { client, controller };
}
async function type(text: string) {
  await act(async () => editor().dispatch({ changes: { from: editor().state.doc.length, insert: text } }));
}
async function input(element: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(element, value);
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("desktop workspace interaction", () => {
  it("collapses the sidebar to icons without replacing the editor or losing a draft", async () => {
    await setup(); await type(" draft");
    const view = editor();
    const sidebar = host.querySelector<HTMLElement>("#workspace-sidebar")!;
    expect(sidebar.querySelector(".sidebar-nav")?.textContent).toContain("Graph");
    const toggle = () => host.querySelector<HTMLButtonElement>('button[aria-controls="workspace-sidebar"]')!;
    await act(async () => toggle().click());
    expect(sidebar.hasAttribute("data-collapsed")).toBe(true);
    expect(sidebar.querySelector(".sidebar-files")).toBeNull();
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(button("Knowledge graph").title).toBe("Graph");
    await act(async () => toggle().click());
    expect(sidebar.hasAttribute("data-collapsed")).toBe(false);
    expect(sidebar.querySelector(".sidebar-files")).not.toBeNull();
    expect(editor()).toBe(view);
    expect(view.state.sliceDoc()).toBe("original draft");
  });
  it("opens vaults through the Finder picker and explains a folder that isn't a vault", async () => {
    const { client } = testClient();
    const controller = new WorkspaceController(client); await mount(controller);
    client.pickFolder.mockResolvedValueOnce("/tmp/missing");
    client.vaultOpen.mockRejectedValueOnce(failure("vault_not_found"));
    await act(async () => window.dispatchEvent(new KeyboardEvent("keydown", { key: "o", metaKey: true })));
    expect(client.pickFolder).toHaveBeenCalledWith("Choose a vault folder");
    expect(client.vaultOpen).toHaveBeenCalledWith("/tmp/missing");
    expect(host.querySelector(".home-error")?.textContent).toContain("No Page vault was found");
    expect(host.querySelectorAll('[role="alert"]')).toHaveLength(1);
    client.pickFolder.mockResolvedValueOnce("/tmp/notes");
    await click("Open Vault");
    expect(client.vaultOpen).toHaveBeenLastCalledWith("/tmp/notes");
    expect(client.vaultCreate).not.toHaveBeenCalled();
  });
  it("switches vaults from the sidebar with the same Finder choices", async () => {
    const { client } = await setup();
    await act(async () => host.querySelector<HTMLButtonElement>(".vault-switcher")!.click());
    const dialog = host.querySelector('[role="dialog"]')!;
    expect(dialog.querySelector("input")).toBeNull();
    client.pickFolder.mockResolvedValueOnce("/tmp/Second Brain");
    const create = [...dialog.querySelectorAll<HTMLButtonElement>(".home-card")].find((b) => b.textContent?.includes("Create a new vault"))!;
    await act(async () => create.click());
    expect(client.vaultCreate).toHaveBeenCalledWith("/tmp/Second Brain", "Second Brain");
    expect(host.querySelector('[role="dialog"]')).toBeNull();
  });
  it("creates and moves through forms with explicit nested paths", async () => {
    const { client, controller } = await setup();
    await click("New Note");
    const dialog = host.querySelector('[role="dialog"]')!;
    const path = dialog.querySelector("input")!;
    await input(path, "nested/new.md");
    await act(async () => dialog.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(client.noteCreate).toHaveBeenCalledWith(vault.id, "nested/new.md", "");
    expect(controller.getState().document?.path).toBe("nested/new.md");
    await click("Rename / Move");
    const moving = host.querySelector('[role="dialog"]')!;
    await input(moving.querySelector("input")!, "archive/new.md");
    await act(async () => moving.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(client.noteMove).toHaveBeenCalledWith(vault.id, note().id, note().revision, "archive/new.md");
    expect(controller.getState().document?.path).toBe("archive/new.md");
    expect(editor().contentDOM.getAttribute("aria-label")).toBe("Markdown: archive/new.md");
  });
  it("disables backend actions in an ordinary browser", async () => {
    await mount(new WorkspaceController(null));
    expect(host.textContent).toContain("Desktop runtime unavailable");
    expect(host.querySelector('[aria-label="Open Vault"]')).toBeNull();
    expect(host.querySelector(".cm-editor")).toBeNull();
  });
  it("Strict Mode initializes once and shows an accessible empty vault", async () => {
    const { client } = testClient(); client.noteList.mockResolvedValue([]);
    const controller = new WorkspaceController(client); await mount(controller);
    await act(async () => { await controller.openVault(vault.root_path); });
    expect(client.backendStart).toHaveBeenCalledTimes(1);
    expect(client.preferencesRead).toHaveBeenCalledTimes(1);
    expect(host.textContent).toContain("No notes yet");
    expect(host.querySelector('[aria-label="Vault and note navigation"]')).not.toBeNull();
  });
  it.each(["", "日本語", "\ufeffhello", "a\nb", "a\r\nb", "a\rb", "no final newline", "has final newline\n"])(
    "serializes source %j through the real editor and PageClient", async (content) => {
      const { client, controller } = await setup(content);
      const view = editor();
      expect(view.state.sliceDoc()).toBe(content);
      await type("🌱"); await click("Save");
      expect(client.noteUpdate).toHaveBeenCalledWith(vault.id, note().id, note().revision, `${content}🌱`);
      expect(isDirty(controller.getState().document)).toBe(false);
      expect(editor()).toBe(view);
    },
  );
  it("keeps selection after saving and clears undo across notes", async () => {
    const { client, controller } = await setup();
    await type("draft");
    await act(async () => editor().dispatch({ selection: { anchor: 3 } }));
    await click("Save"); expect(editor().state.selection.main.anchor).toBe(3);
    client.noteRead.mockResolvedValueOnce(note("33333333-3333-4333-8333-333333333333", "other"));
    await act(async () => { await controller.selectNote("33333333-3333-4333-8333-333333333333"); });
    expect(undo(editor())).toBe(false);
    expect(host.querySelectorAll(".cm-editor")).toHaveLength(1);
  });
  it("mixed endings stay read-only until explicit confirmed conversion", async () => {
    const { client, controller } = await setup("\ufeffa\r\nb\rc\nlast");
    expect(editor().contentDOM.getAttribute("contenteditable")).toBe("false");
    await click("Convert to LF"); await click("Cancel", host.querySelector('[role="dialog"]')!);
    expect(controller.getState().document?.mixed).toBe(true);
    expect(client.noteUpdate).not.toHaveBeenCalled();
    await click("Convert to LF"); await click("Confirm Conversion"); await click("Save");
    expect(client.noteUpdate).toHaveBeenCalledWith(vault.id, note().id, note().revision, "\ufeffa\nb\nc\nlast");
  });
  it.each(["\n", "\r\n", "\r"])("normalizes pasted breaks to the source separator %j", async (separator) => {
    const { client } = await setup(`a${separator}b`);
    await type("\r\npaste\nmore\rlast"); await click("Save");
    expect(client.noteUpdate).toHaveBeenCalledWith(vault.id, note().id, note().revision, `a${separator}b${separator}paste${separator}more${separator}last`);
  });
  it("dirty navigation and quit support Cancel, Discard and Save", async () => {
    const { client, controller } = await setup(); await type("draft");
    await click("Close Vault"); await click("Cancel", host.querySelector('[role="dialog"]')!);
    expect(controller.getState().document?.draft).toBe("originaldraft");
    expect(client.vaultClose).not.toHaveBeenCalled();
    await click("Quit Page"); await click("Cancel", host.querySelector('[role="dialog"]')!);
    expect(client.desktopQuit).not.toHaveBeenCalled();
    await click("New Note"); await click("Discard", host.querySelector('[role="dialog"]')!);
    expect(host.textContent).toContain("Relative note path"); expect(client.noteUpdate).not.toHaveBeenCalled();
    await click("Cancel", host.querySelector('[role="dialog"]')!);
    await type("again"); await click("Close Vault"); await click("Save", host.querySelector('[role="dialog"]')!);
    expect(client.vaultClose).toHaveBeenCalledTimes(1); expect(client.noteUpdate).toHaveBeenCalledTimes(1);
  });
  it("permanent delete names the path; cancel sends no request", async () => {
    const { client } = await setup(); await click("Delete Note");
    const dialog = host.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain("a.md"); expect(dialog.textContent).toContain("There is no trash or undo");
    await click("Cancel", dialog); expect(client.noteDelete).not.toHaveBeenCalled();
    await click("Delete Note"); await click("Permanently Delete");
    expect(client.noteDelete).toHaveBeenCalledWith(vault.id, note().id, note().revision);
    expect(host.querySelector(".cm-editor")).toBeNull();
  });
  it("repeated save shortcuts submit once and retain typing during pending save", async () => {
    const { client, controller } = await setup();
    const pending = deferred<NoteResponse>(); client.noteUpdate.mockReturnValueOnce(pending.promise);
    await type("first");
    await act(async () => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "s", metaKey: true }));
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "s", metaKey: true }));
    });
    await type("later"); await act(async () => pending.resolve(note(undefined, "originalfirst")));
    expect(client.noteUpdate).toHaveBeenCalledTimes(1);
    expect(controller.getState().document?.draft).toBe("originalfirstlater");
    expect(host.textContent).toContain("Unsaved changes");
  });
  it("conflict reload requires a separate discard confirmation", async () => {
    const { client, controller } = await setup(); await type("mine");
    client.noteUpdate.mockRejectedValueOnce(failure("revision_conflict"));
    client.noteRead.mockResolvedValueOnce({ ...note(undefined, "disk"), revision: "c".repeat(64) });
    await click("Save");
    expect(host.querySelector('[aria-label="Current disk content"]')?.textContent).toBe("disk");
    await click("Reload from Disk"); await click("Cancel", host.querySelector('[role="dialog"]')!);
    expect(controller.getState().document?.draft).toBe("originalmine");
    await click("Reload from Disk"); await click("Discard and Reload");
    expect(editor().state.sliceDoc()).toBe("disk");
  });
  it("overwrite requires explicit confirmation and can conflict again", async () => {
    const { client, controller } = await setup(); await type("mine");
    client.noteUpdate.mockRejectedValueOnce(failure("revision_conflict"));
    client.noteRead.mockResolvedValueOnce({ ...note(undefined, "disk"), revision: "c".repeat(64) });
    await click("Save"); await click("Use My Draft"); await click("Cancel", host.querySelector('[role="dialog"]')!);
    expect(client.noteUpdate).toHaveBeenCalledTimes(1);
    await click("Use My Draft");
    client.noteUpdate.mockRejectedValueOnce(failure("revision_conflict"));
    client.noteRead.mockResolvedValueOnce({ ...note(undefined, "disk again"), revision: "d".repeat(64) });
    await click("Confirm Overwrite");
    expect(client.noteUpdate).toHaveBeenLastCalledWith(vault.id, note().id, "c".repeat(64), "originalmine");
    expect(controller.getState().document?.draft).toBe("originalmine");
    expect(host.querySelector('[aria-label="Current disk content"]')?.textContent).toBe("disk again");
  });
  it("unknown delete remains visible and cannot be repeated", async () => {
    const { client, controller } = await setup();
    client.noteDelete.mockRejectedValueOnce(failure("mutation_outcome_unknown"));
    await click("Delete Note"); await click("Permanently Delete");
    expect(controller.getState().unknown?.attempt.operation).toBe("delete");
    expect(controller.getState().document).not.toBeNull();
    expect(button("Permanently Delete").disabled).toBe(true);
    await click("Cancel", host.querySelector('[role="dialog"]')!);
    client.noteList.mockResolvedValueOnce([]); await click("Verify Outcome");
    expect(controller.getState().document).toBeNull(); expect(client.noteDelete).toHaveBeenCalledTimes(1);
  });
  it("dialogs contain focus and restore it on cancellation", async () => {
    await setup(); const previous = button("Delete Note"); previous.focus(); await click("Delete Note");
    const dialog = host.querySelector('[role="dialog"]')!;
    const cancel = button("Cancel", dialog); cancel.focus();
    await act(async () => cancel.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true })));
    expect(document.activeElement).toBe(button("Permanently Delete"));
    await act(async () => document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(document.activeElement).toBe(previous);
  });
});
