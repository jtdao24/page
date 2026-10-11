// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Workspace } from "./Workspace";
import { Intro } from "./Intro";
import { WorkspaceController } from "../workspace/controller";
import { note, testClient, vault } from "../workspace/testClient";
import { SAMPLE_NOTES } from "../workspace/sample";

let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect() {} });
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals(); });
const card = (title: string) => [...host.querySelectorAll<HTMLButtonElement>(".home-card")].find((b) => b.textContent?.includes(title))!;
async function mount() {
  const { client } = testClient();
  const controller = new WorkspaceController(client);
  const intro = vi.fn();
  await act(async () => root.render(<Workspace controller={controller} onShowIntro={intro} />));
  await act(async () => { await controller.start(); });
  return { client, controller, intro };
}

describe("home screen", () => {
  it("offers clear choices and a tour link, with no path typing", async () => {
    const { intro } = await mount();
    expect(host.querySelector(".home-hero h2")?.textContent).toBe("Welcome to Page");
    expect([...host.querySelectorAll(".home-card-title")].map((t) => t.textContent)).toEqual(
      ["Start with a sampleRecommended", "Create a new vault", "Open a vault"]);
    await act(async () => host.querySelector<HTMLButtonElement>(".link-button")!.click());
    expect(intro).toHaveBeenCalledTimes(1);
    expect(host.querySelector(".home input")).toBeNull();
  });
  it("does nothing when the folder picker is cancelled", async () => {
    const { client } = await mount();
    await act(async () => card("Open a vault").click());
    expect(client.pickFolder).toHaveBeenCalledWith("Choose a vault folder");
    expect(client.vaultOpen).not.toHaveBeenCalled();
  });
  it("creates a vault named after the chosen folder, or opens one", async () => {
    const { client } = await mount();
    client.pickFolder.mockResolvedValueOnce("/Users/me/Projects/Thesis");
    await act(async () => card("Create a new vault").click());
    expect(client.vaultCreate).toHaveBeenCalledWith("/Users/me/Projects/Thesis", "Thesis");
  });
  it("builds a sample vault of linked starter notes and opens the welcome note", async () => {
    const { client, controller } = await mount();
    client.pickFolder.mockResolvedValueOnce("/Users/me/Page Sample");
    const created = SAMPLE_NOTES.map((sample, index) => note(`a000000${index}-0000-4000-8000-000000000000`, sample.content, sample.path));
    client.noteCreate.mockImplementation(async (_vault, path) => created.find((item) => item.relative_path === path)!);
    client.noteList.mockResolvedValue(created);
    client.noteRead.mockImplementation(async (_vault, id) => created.find((item) => item.id === id)!);
    await act(async () => card("Start with a sample").click());
    expect(client.vaultCreate).toHaveBeenCalledWith("/Users/me/Page Sample", "Page Sample");
    expect(client.noteCreate.mock.calls.map((call) => call[1])).toEqual(SAMPLE_NOTES.map((sample) => sample.path));
    expect(controller.getState().document?.path).toBe("Welcome to Page.md");
    for (const sample of SAMPLE_NOTES) expect(sample.content).toMatch(/\[\[[^\]]+\]\]/);
  });
  it("keeps the user's file when a sample note's name is already taken", async () => {
    const { client, controller } = await mount();
    client.pickFolder.mockResolvedValueOnce("/Users/me/Notes");
    client.noteCreate.mockRejectedValueOnce({ kind: "api", status: 409, code: "note_exists", message: "exists", details: null });
    await act(async () => card("Start with a sample").click());
    expect(client.noteCreate).toHaveBeenCalledTimes(SAMPLE_NOTES.length);
    expect(controller.getState().vault?.id).toBe(vault.id);
  });
  it("stops and reports other errors while creating sample notes", async () => {
    const { client, controller } = await mount();
    client.pickFolder.mockResolvedValueOnce("/Users/me/Notes");
    client.noteCreate.mockRejectedValueOnce({ kind: "api", status: 503, code: "storage_unavailable", message: "Storage is unavailable.", details: null });
    await act(async () => card("Start with a sample").click());
    expect(client.noteCreate).toHaveBeenCalledTimes(1);
    expect(controller.getState().actionError?.error.code).toBe("storage_unavailable");
  });
  it("shows quick actions when a vault is open but no note is selected", async () => {
    const { client, controller } = await mount();
    client.noteList.mockResolvedValue([]);
    await act(async () => { await controller.openVault(vault.root_path); });
    expect([...host.querySelectorAll(".quick-action span")].map((s) => s.textContent)).toEqual(
      ["Write a new note", "Save a web page", "See how notes connect", "Ask your notes"]);
    expect(host.querySelector(".welcome-tip")?.textContent).toContain("page-test");
  });
});

describe("recent vaults", () => {
  const other = { vault_id: "22222222-2222-4222-8222-222222222222", root_path: "/Users/me/Thesis", last_note_id: null };
  it("removes a vault from recent without touching its folder, and clears it as the active vault", async () => {
    const { client } = testClient();
    client.preferencesRead.mockResolvedValue({ version: 1, recent_vaults: [other], active_vault_id: other.vault_id });
    client.vaultOpen.mockRejectedValueOnce({ kind: "api", status: 404, code: "vault_not_found", message: "gone", details: null });
    const controller = new WorkspaceController(client);
    await act(async () => root.render(<Workspace controller={controller} />));
    await act(async () => { await controller.start(); });
    const remove = host.querySelector<HTMLButtonElement>('[aria-label="Remove Thesis from recent"]')!;
    await act(async () => remove.click());
    await act(async () => { await controller.flushPreferences(); });
    expect(host.querySelector(".home-recents")).toBeNull();
    expect(client.preferencesWrite).toHaveBeenLastCalledWith({ version: 1, recent_vaults: [], active_vault_id: null });
    expect(client.vaultClose).not.toHaveBeenCalled();
  });
  it("lets other vaults be removed from the sidebar but keeps the open one", async () => {
    const { client } = testClient();
    client.preferencesRead.mockResolvedValue({ version: 1, recent_vaults: [other], active_vault_id: null });
    const controller = new WorkspaceController(client);
    await act(async () => root.render(<Workspace controller={controller} />));
    await act(async () => { await controller.start(); await controller.openVault(vault.root_path); });
    expect(host.querySelector(`[aria-label="Remove ${vault.root_path} from recent"]`)).toBeNull();
    await act(async () => host.querySelector<HTMLButtonElement>(`[aria-label="Remove ${other.root_path} from recent"]`)!.click());
    expect(controller.getState().preferences.recent_vaults.map((entry) => entry.vault_id)).toEqual([vault.id]);
    controller.forgetRecent(vault.id);
    expect(controller.getState().preferences.recent_vaults).toHaveLength(1);
  });
});

describe("intro tour", () => {
  it("steps forward and back with buttons, dots and arrow keys, then finishes", async () => {
    const done = vi.fn();
    await act(async () => root.render(<Intro onDone={done} />));
    const title = () => host.querySelector(".intro-slide h2")?.textContent;
    expect(title()).toBe("Welcome to Page");
    const next = host.querySelector<HTMLButtonElement>(".intro-next")!;
    expect(document.activeElement).toBe(next);
    await act(async () => next.click());
    expect(title()).toBe("Your notes are just files");
    expect(host.querySelector(".intro-slide")?.className).toContain("is-forward");
    const panel = host.querySelector(".intro-backdrop")!;
    await act(async () => panel.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true })));
    expect(title()).toBe("Welcome to Page");
    await act(async () => host.querySelectorAll<HTMLButtonElement>(".intro-dots button")[4].click());
    expect(title()).toBe("Bring everything in");
    expect(next.textContent).toBe("Get started");
    await act(async () => next.click());
    expect(done).toHaveBeenCalledTimes(1);
    await act(async () => panel.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })));
    expect(done).toHaveBeenCalledTimes(2);
    const skip = host.querySelector<HTMLButtonElement>(".intro-skip")!;
    next.focus();
    await act(async () => next.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true })));
    expect(document.activeElement).toBe(skip);
    await act(async () => skip.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true })));
    expect(document.activeElement).toBe(next);
  });
});

describe("first launch", () => {
  it("shows the intro once, then remembers it was seen", async () => {
    const { default: App } = await import("../App");
    const { INTRO_SEEN_KEY } = await import("./Intro");
    localStorage.removeItem(INTRO_SEEN_KEY);
    await act(async () => root.render(<App />));
    expect(host.querySelector(".intro-backdrop")).not.toBeNull();
    await act(async () => host.querySelector<HTMLButtonElement>(".intro-skip")!.click());
    expect(host.querySelector(".intro-backdrop")).toBeNull();
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
    await act(async () => root.unmount());
    root = createRoot(host);
    await act(async () => root.render(<App />));
    expect(host.querySelector(".intro-backdrop")).toBeNull();
    localStorage.removeItem(INTRO_SEEN_KEY);
  });
});
