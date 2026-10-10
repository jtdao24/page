// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { entryGraph } from "./graph";
import { collectionOf, PREVIEW_NOTES } from "./library";
import { noteHeadings } from "./noteReader";

const core = vi.hoisted(() => ({ session: null as string | null, notes: null as typeof PREVIEW_NOTES | null,
  status: null, error: null, pending: false, connect: vi.fn(), disconnect: vi.fn(), index: vi.fn() }));
vi.mock("./useCore", () => ({ CORE_URL: "http://127.0.0.1:8765", useCore: () => core }));
beforeEach(() => {
  core.session = null; core.notes = null;
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", { configurable: true, value: () => {} });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function (this: HTMLDialogElement) { this.setAttribute("open", ""); } });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });
const panel = (title: string) => within(screen.getByRole("tabpanel", { name: title }));
const dragData = () => ({ effectAllowed: "none", dropEffect: "none", setData: vi.fn() });
function dropInPane(title: string, side: "left" | "right") {
  const dataTransfer = dragData();
  fireEvent.dragStart(screen.getByRole("tab", { name: title }), { dataTransfer });
  const target = screen.getByRole("group", { name: `Drop tab in ${side} pane` });
  fireEvent.dragOver(target, { dataTransfer });
  expect(dataTransfer.dropEffect).toBe("move");
  fireEvent.drop(target, { dataTransfer });
}

describe("split workspace", () => {
  it.each(["left", "right"] as const)("drags an entry to the %s side while keeping the graph visible", async (side) => {
    const user = userEvent.setup(); render(<App />);
    const note = PREVIEW_NOTES[0];
    await user.click(screen.getByRole("button", { name: `Read ${note.title}` }));
    const originalPanel = screen.getByRole("tabpanel", { name: note.title });
    originalPanel.scrollTop = 120;
    await user.click(panel(note.title).getByRole("button", { name: "Markdown source" }));
    dropInPane(note.title, side);
    expect(screen.getAllByRole("tabpanel")).toHaveLength(2);
    expect(within(screen.getByRole("tablist", { name: `${side === "left" ? "Left" : "Right"} pane tabs` })).getByRole("tab", { name: note.title })).toBeTruthy();
    expect(screen.getByRole("tabpanel", { name: note.title })).toBe(originalPanel);
    expect(originalPanel.scrollTop).toBe(120);
    expect(panel(note.title).getByLabelText("Markdown source")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Graph" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByRole("group", { name: /Drop tab/ })).toBeNull();
  });
  it("switches independently, opens new entries in the focused pane and reuses entries across panes", async () => {
    const user = userEvent.setup(); render(<App />);
    const [a, b, c] = PREVIEW_NOTES;
    await user.click(screen.getByRole("button", { name: `Read ${a.title}` }));
    await user.click(screen.getByRole("button", { name: `Read ${b.title}` }));
    dropInPane(b.title, "right");
    await user.click(screen.getByRole("tab", { name: "Graph" }));
    expect(panel(b.title).getByText(b.excerpt)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: `Open ${c.title}` }));
    const left = within(screen.getByRole("tablist", { name: "Left pane tabs" }));
    const right = within(screen.getByRole("tablist", { name: "Right pane tabs" }));
    expect(left.getByRole("tab", { name: c.title })).toBeTruthy();
    await user.click(screen.getByRole("tab", { name: b.title }));
    await user.click(screen.getByRole("button", { name: `Read ${a.title}` }));
    expect(left.getByRole("tab", { name: a.title }).getAttribute("aria-selected")).toBe("true");
    expect(right.getByRole("tab", { name: b.title }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getAllByRole("tab")).toHaveLength(4);
    await user.click(screen.getByRole("tab", { name: b.title }));
    // Opening a new entry from the sidebar targets the selected right pane.
    await user.click(screen.getByRole("button", { name: `Read ${PREVIEW_NOTES[3].title}` }));
    expect(right.getByRole("tab", { name: PREVIEW_NOTES[3].title })).toBeTruthy();
  });
  it("moves tabs via a tab strip and collapses a pane when its last tab moves back", async () => {
    const user = userEvent.setup(); render(<App />);
    const [a, b] = PREVIEW_NOTES;
    await user.click(screen.getByRole("button", { name: `Read ${a.title}` }));
    await user.click(screen.getByRole("button", { name: `Read ${b.title}` }));
    dropInPane(b.title, "right");
    const dataTransfer = dragData();
    fireEvent.dragStart(screen.getByRole("tab", { name: a.title }), { dataTransfer });
    fireEvent.drop(screen.getByRole("tablist", { name: "Right pane tabs" }), { dataTransfer });
    expect(within(screen.getByRole("tablist", { name: "Right pane tabs" })).getAllByRole("tab")).toHaveLength(2);
    dropInPane(a.title, "left");
    dropInPane(b.title, "left");
    expect(screen.getByRole("tablist", { name: "Workspace tabs" })).toBeTruthy();
    expect(screen.getAllByRole("tabpanel")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: b.title }).getAttribute("aria-selected")).toBe("true");
  });
  it("collapses either empty pane on close and never closes the graph", async () => {
    const user = userEvent.setup(); render(<App />);
    const note = PREVIEW_NOTES[0];
    await user.click(screen.getByRole("button", { name: `Read ${note.title}` }));
    dropInPane(note.title, "left");
    await user.click(screen.getByRole("button", { name: `Close ${note.title} tab` }));
    expect(screen.getByRole("tablist", { name: "Workspace tabs" })).toBeTruthy();
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: `Read ${note.title}` }));
    dropInPane(note.title, "right");
    await user.click(screen.getByRole("button", { name: `Close ${note.title} tab` }));
    expect(screen.getByRole("tablist", { name: "Workspace tabs" })).toBeTruthy();
    expect(screen.getAllByRole("tab")).toHaveLength(1);
  });
  it("supports keyboard splitting/moving and confines arrow navigation to the current pane", async () => {
    const user = userEvent.setup(); render(<App />);
    expect((screen.getByRole("button", { name: "Split active tab to right" }) as HTMLButtonElement).disabled).toBe(true);
    const [a, b] = PREVIEW_NOTES;
    await user.click(screen.getByRole("button", { name: `Read ${a.title}` }));
    await user.click(screen.getByRole("button", { name: `Read ${b.title}` }));
    screen.getByRole("button", { name: "Split active tab to right" }).focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tab", { name: b.title })));
    await user.keyboard("{Home}{ArrowRight}");
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: b.title }));
    await user.click(screen.getByRole("tab", { name: "Graph" }));
    await user.keyboard("{End}");
    expect(document.activeElement).toBe(screen.getByRole("tab", { name: a.title }));
    const rightHeader = screen.getByRole("tablist", { name: "Right pane tabs" }).parentElement!;
    await user.click(within(rightHeader).getByRole("button", { name: "Move active tab to other pane" }));
    expect(screen.getByRole("tablist", { name: "Workspace tabs" })).toBeTruthy();
  });
  it("cancels drags and ignores external or old-session drops", async () => {
    const user = userEvent.setup(); const app = render(<App />);
    const note = PREVIEW_NOTES[0];
    await user.click(screen.getByRole("button", { name: `Read ${note.title}` }));
    const tab = screen.getByRole("tab", { name: note.title });
    const dataTransfer = dragData();
    fireEvent.dragStart(tab, { dataTransfer });
    expect(screen.getByRole("group", { name: "Drop tab in right pane" })).toBeTruthy();
    fireEvent.dragEnd(tab);
    expect(screen.queryByRole("group", { name: /Drop tab/ })).toBeNull();
    expect(fireEvent.drop(screen.getByRole("tablist"), { dataTransfer })).toBe(false);
    expect(screen.getAllByRole("tablist")).toHaveLength(1);
    fireEvent.dragStart(tab, { dataTransfer });
    core.session = "different-vault"; core.notes = []; app.rerender(<App />);
    expect(screen.queryByRole("group", { name: /Drop tab/ })).toBeNull();
    fireEvent.drop(screen.getByRole("tablist"), { dataTransfer });
    expect(screen.getAllByRole("tab")).toHaveLength(1);
  });
  it("keeps an in-flight note read mounted when moved between panes", async () => {
    const note = PREVIEW_NOTES[0]; core.session = "test-token"; core.notes = [note];
    let finish: (response: Response) => void = () => {};
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: `Read ${note.title}` }));
    dropInPane(note.title, "right");
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(false);
    await act(async () => finish(new Response(JSON.stringify({ note: { ...note, content: "# Full entry\n\nStill the same request." } }))));
    expect(panel(note.title).getByText("Still the same request.")).toBeTruthy();
    dropInPane(note.title, "left");
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(panel(note.title).getByText("Still the same request.")).toBeTruthy();
  });
  it("moves the graph without remounting it or losing filters and zoom", async () => {
    const user = userEvent.setup(); render(<App />);
    await user.type(screen.getByRole("searchbox"), "creative");
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    const canvas = screen.getByRole("group", { name: "Graph canvas" });
    await user.click(screen.getByRole("button", { name: `Read ${PREVIEW_NOTES[0].title}` }));
    dropInPane("Graph", "right");
    expect(screen.getByRole("group", { name: "Graph canvas" })).toBe(canvas);
    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("creative");
    expect(screen.getByLabelText("Graph zoom").textContent).toBe("125%");
    expect(screen.getAllByRole("tabpanel")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Close Graph tab" })).toBeNull();
    dropInPane("Graph", "left");
    expect(screen.getAllByRole("tablist")).toHaveLength(1);
    expect(screen.getByRole("group", { name: "Graph canvas" })).toBe(canvas);
  });
});

describe("entry network", () => {
  it("pans on background drag and resets the camera without opening an entry", async () => {
    vi.stubGlobal("PointerEvent", MouseEvent);
    const user = userEvent.setup(); render(<App />);
    const canvas = screen.getByRole("group", { name: "Graph canvas" });
    Object.defineProperty(canvas, "setPointerCapture", { value: vi.fn() });
    const world = canvas.querySelector<HTMLElement>(".graph-world")!;
    const original = world.style.transform;
    fireEvent.pointerDown(canvas, { button: 0, clientX: 20, clientY: 30 });
    fireEvent.pointerMove(canvas, { clientX: 70, clientY: 90 });
    fireEvent.pointerUp(canvas);
    expect(world.style.transform).not.toBe(original);
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Reset view" }));
    expect(world.style.transform).toBe(original);
  });
  it("uses one real entry per node and only shared-collection connections with deterministic layout", () => {
    const graph = entryGraph(PREVIEW_NOTES);
    expect(graph).toEqual(entryGraph([...PREVIEW_NOTES].reverse()));
    expect(new Set(graph.nodes.map((node) => node.note.id)).size).toBe(8);
    expect(graph.edges.every((edge) => collectionOf(edge.from.note) === collectionOf(edge.to.note))).toBe(true);
    expect(new Set(graph.edges.map((edge) => edge.key)).size).toBe(graph.edges.length);
    expect(graph.edges.length).toBeLessThan(2 * PREVIEW_NOTES.length);
    expect(entryGraph([]).nodes).toEqual([]);
  });
  it("shows all entries, filters by text and collection, and resets zoom", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(screen.getAllByRole("button", { name: /^Open / })).toHaveLength(8);
    expect(screen.getByText(/Lines connect entries in the same collection/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(screen.getByLabelText("Graph zoom").textContent).toBe("125%");
    await user.click(screen.getByRole("button", { name: "Reset view" }));
    expect(screen.getByLabelText("Graph zoom").textContent).toBe("100%");
    await user.type(screen.getByRole("searchbox"), "creative");
    expect(screen.getAllByRole("button", { name: /^Open / })).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Reading" }));
    expect(screen.getByText("No matching entries")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getAllByRole("button", { name: /^Open / })).toHaveLength(8);
  });
});

describe("workspace tabs", () => {
  it("opens each node in its own tab and reuses an existing tab", async () => {
    const user = userEvent.setup();
    render(<App />);
    for (const note of PREVIEW_NOTES) {
      await user.click(screen.getByRole("button", { name: `Open ${note.title}` }));
      expect(screen.getByRole("tab", { name: note.title }).getAttribute("aria-selected")).toBe("true");
      expect(panel(note.title).getByText(note.excerpt)).toBeTruthy();
      expect(screen.queryByRole("dialog")).toBeNull();
      await user.click(screen.getByRole("tab", { name: "Graph" }));
    }
    expect(screen.getAllByRole("tab")).toHaveLength(9);
    await user.click(screen.getByRole("button", { name: `Open ${PREVIEW_NOTES[0].title}` }));
    expect(screen.getAllByRole("tab")).toHaveLength(9);
  });
  it("preserves graph filters and each entry's source mode while switching tabs", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByRole("searchbox"), "creative");
    await user.click(screen.getByRole("button", { name: "Open Creative connections" }));
    await user.click(screen.getByRole("button", { name: "Markdown source" }));
    await user.click(screen.getByRole("button", { name: `Read ${PREVIEW_NOTES[0].title}` }));
    await user.click(screen.getByRole("tab", { name: "Creative connections" }));
    expect(panel("Creative connections").getByLabelText("Markdown source").textContent).toContain("# Creative connections");
    await user.click(screen.getByRole("tab", { name: "Graph" }));
    expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe("creative");
    expect(screen.getAllByRole("button", { name: /^Open / })).toHaveLength(1);
  });
  it("closes background and active tabs with a predictable fallback to the graph", async () => {
    const user = userEvent.setup();
    render(<App />);
    const [a, b] = PREVIEW_NOTES;
    await user.click(screen.getByRole("button", { name: `Read ${a.title}` }));
    await user.click(screen.getByRole("button", { name: `Read ${b.title}` }));
    await user.click(screen.getByRole("button", { name: `Close ${a.title} tab` }));
    expect(screen.getByRole("tab", { name: b.title }).getAttribute("aria-selected")).toBe("true");
    await user.click(screen.getByRole("button", { name: `Close ${b.title} tab` }));
    expect(screen.getAllByRole("tab")).toHaveLength(1);
    expect(screen.getByRole("tab", { name: "Graph" }).getAttribute("aria-selected")).toBe("true");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tab", { name: "Graph" })));
  });
  it("supports keyboard node activation, arrow navigation, Home/End and Delete", async () => {
    const user = userEvent.setup();
    render(<App />);
    const [a, b] = PREVIEW_NOTES;
    screen.getByRole("button", { name: `Open ${a.title}` }).focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("tab", { name: a.title })));
    await user.click(screen.getByRole("button", { name: `Read ${b.title}` }));
    const graph = screen.getByRole("tab", { name: "Graph" });
    await user.click(graph);
    await user.keyboard("{End}");
    expect(screen.getByRole("tab", { name: b.title }).getAttribute("aria-selected")).toBe("true");
    await user.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: a.title }).getAttribute("aria-selected")).toBe("true");
    await user.keyboard("{Home}");
    expect(graph.getAttribute("aria-selected")).toBe("true");
    await user.keyboard("{End}{Delete}");
    expect(screen.queryByRole("tab", { name: b.title })).toBeNull();
  });
  it("brings entry questions into the local draft without sending or closing the entry", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: `Open ${PREVIEW_NOTES[0].title}` }));
    await user.click(screen.getByRole("button", { name: /Ask about this entry/ }));
    const composer = screen.getByLabelText("Ask a question about your context") as HTMLTextAreaElement;
    expect(composer.value).toContain(PREVIEW_NOTES[0].title);
    await waitFor(() => expect(document.activeElement).toBe(composer));
    expect(localStorage.getItem("page.question-draft")).toBe(composer.value);
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("full note content in tabs", () => {
  it("refreshes an entry from the current Markdown source", async () => {
    const note = PREVIEW_NOTES[0]; core.session = "test-token"; core.notes = [note];
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response(JSON.stringify({ note: { ...note, content: "# First read" } })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ note: { ...note, content: "# Updated source" } })));
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: `Open ${note.title}` }));
    await screen.findByRole("heading", { name: "First read" });
    await user.click(screen.getByRole("button", { name: "Refresh entry" }));
    expect(await screen.findByRole("heading", { name: "Updated source" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "First read" })).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("loads full authenticated Markdown and safely renders formatting", async () => {
    const note = PREVIEW_NOTES[0]; core.session = "test-reader-token"; core.notes = [note];
    let finish: (response: Response) => void = () => {};
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: `Open ${note.title}` }));
    expect(screen.getByText("Opening your entry…")).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith(`http://127.0.0.1:8765/api/context/${note.id}`, expect.objectContaining({ headers: { Authorization: "Bearer test-reader-token" } }));
    const content = `# Full note\n\n${"A sentence. ".repeat(60)}\n\n## Last section\n\nWords beyond the excerpt.\n\n| Column | Value |\n| --- | --- |\n| A | B |\n\n<script>alert(1)</script>\n\n![Remote](https://example.com/track.png)\n\n[Unsafe](javascript:alert(1))`;
    await act(async () => finish(new Response(JSON.stringify({ note: { ...note, content } }))));
    expect(panel(note.title).getByText("Words beyond the excerpt.")).toBeTruthy();
    expect(panel(note.title).getByRole("table")).toBeTruthy();
    expect(document.querySelector("script")).toBeNull(); expect(document.querySelector("img")).toBeNull();
    expect(screen.queryByRole("link", { name: "Unsafe" })).toBeNull(); expect(localStorage.length).toBe(0);
    await user.click(screen.getByRole("tab", { name: "Graph" }));
    await user.click(screen.getByRole("tab", { name: note.title }));
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("retries failed reads without substituting samples and reads empty files as empty", async () => {
    const note = PREVIEW_NOTES[1]; core.session = "test-token"; core.notes = [note];
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(new Response("{}", { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ note: { ...note, content: "" } })));
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: `Open ${note.title}` }));
    expect((await screen.findByRole("alert")).textContent).toContain("Index your vault changes");
    expect(screen.queryByText(note.excerpt)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("A blank page, full of possibility.")).toBeTruthy();
  });
  it("aborts closed tabs and clears old vault tabs on connection changes, ignoring late responses", async () => {
    const note = PREVIEW_NOTES[0]; core.session = "first-session"; core.notes = [note];
    const finishes: ((response: Response) => void)[] = [];
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise<Response>((resolve) => finishes.push(resolve)));
    const user = userEvent.setup(); const app = render(<App />);
    await user.click(screen.getByRole("button", { name: `Open ${note.title}` }));
    await user.click(screen.getByRole("button", { name: `Close ${note.title} tab` }));
    expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true);
    await user.click(screen.getByRole("button", { name: `Open ${note.title}` }));
    core.session = "second-session"; app.rerender(<App />);
    expect(fetch.mock.calls[1][1]?.signal?.aborted).toBe(true);
    await act(async () => finishes.forEach((finish) => finish(new Response(JSON.stringify({ note: { ...note, content: "Private old note" } })))));
    expect(screen.getAllByRole("tab")).toHaveLength(1); expect(screen.queryByText("Private old note")).toBeNull();
  });
  it("keeps heading and footnote IDs unique across mounted tabs and navigates within the current entry", async () => {
    const [a, b] = PREVIEW_NOTES; core.session = "test-token"; core.notes = [a, b];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
      const note = String(url).endsWith(a.id) ? a : b;
      return new Response(JSON.stringify({ note: { ...note, content: "# Same\n\n## Section\n\nA footnote[^1].\n\n[^1]: A reference." } }));
    });
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: `Read ${a.title}` })); await screen.findByRole("heading", { name: "Section" });
    await user.click(screen.getByRole("button", { name: `Read ${b.title}` })); await screen.findByRole("heading", { name: "Section" });
    const ids = Array.from(document.querySelectorAll("[id]")).map((element) => element.id);
    expect(new Set(ids).size).toBe(ids.length);
    const scroll = vi.spyOn(HTMLElement.prototype, "scrollIntoView").mockImplementation(() => {});
    await user.click(panel(b.title).getByRole("button", { name: "Section" }));
    expect(document.activeElement?.id).toBe(`entry-${b.id}-section-3`);
    await user.click(panel(b.title).getByRole("link", { name: "1" }));
    expect(screen.getByRole("tabpanel", { name: b.title }).contains(scroll.mock.instances.at(-1) as Node)).toBe(true);
  });
  it("parses actual headings, ignoring fenced code and preserving duplicate headings", () => {
    expect(noteHeadings("Title\n=====\n\n```md\n# Not a heading\n```\n\n## Same\n\n## Same")).toEqual([
      { id: "page-section-1", title: "Title", level: 1 }, { id: "page-section-8", title: "Same", level: 2 }, { id: "page-section-10", title: "Same", level: 2 },
    ]);
  });
});

describe("compact navigation", () => {
  it("remembers sidebar collapse and retains account/settings tools", async () => {
    const user = userEvent.setup(); const app = render(<App />);
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.queryByRole("complementary", { name: "Vault navigation" })).toBeNull();
    expect(localStorage.getItem("page.sidebar-collapsed")).toBe("true");
    expect(screen.getByRole("button", { name: "Vault settings" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Profile and account settings" })).toBeTruthy();
    app.unmount(); render(<App />);
    await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(screen.getByRole("complementary", { name: "Vault navigation" })).toBeTruthy();
  });
  it("uses the sidebar shortcut and returns from entry tabs to search the graph", async () => {
    const user = userEvent.setup(); render(<App />);
    fireEvent.keyDown(window, { key: "\\", metaKey: true });
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeTruthy();
    fireEvent.keyDown(window, { key: "\\", ctrlKey: true });
    await user.click(screen.getByRole("button", { name: `Read ${PREVIEW_NOTES[0].title}` }));
    await user.click(screen.getByRole("button", { name: "Focus library search" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("searchbox")));
    expect(screen.getByRole("tab", { name: "Graph" }).getAttribute("aria-selected")).toBe("true");
  });
});
