// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { NoteResponse, SemanticSearchHit, SemanticSearchResponse } from "./api/types";
import { byteRangeToCharRange } from "./byteRange";
import SemanticSearchPanel from "./components/SemanticSearchPanel";

const content = "Intro ☕\n\n# Logic\n\nUse a Karnaugh map.\n";
const start = new TextEncoder().encode("Intro ☕\n\n").length;

function hit(path: string, score: number, excerpt: string): SemanticSearchHit {
  return {
    note_id: `id-${path}`,
    path,
    title: path.replace(/\.md$/, ""),
    score,
    excerpt,
    chunk: { id: 1, ordinal: 1, start_byte: start, end_byte: new TextEncoder().encode(content).length - 1, heading: "Logic" },
    matched_chunks: 2,
  };
}

function searchResponse(query: string, results: SemanticSearchHit[]): SemanticSearchResponse {
  return { query, limit: 10, metric: "cosine", model: "test", results };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function search(query: string) {
  fireEvent.change(screen.getByLabelText("Search notes by meaning"), { target: { value: query } });
  fireEvent.submit(screen.getByRole("search"));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("App", () => {
  it("renders the Page heading and search box", () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain(">Page</h1>");
    expect(html).toContain("Search notes by meaning");
  });

  it("searches, shows ranked note results, and opens the clicked note at its passage", async () => {
    const note: NoteResponse = { id: "id-logic.md", path: "logic.md", title: "logic", content, updated_at: "2026-10-09T00:00:00Z" };
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/api/search/semantic")) {
        expect(JSON.parse(String(init?.body))).toEqual({ query: "simplify a circuit", limit: 10 });
        return json(searchResponse("simplify a circuit", [hit("logic.md", 0.71, "# Logic"), hit("gates.md", 0.42, "Gates")]));
      }
      expect(url).toContain("/api/note?path=logic.md");
      return json(note);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    search("  simplify a circuit ");
    const list = await screen.findByRole("list", { name: "Search results" });
    const items = within(list).getAllByRole("button");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("logic"),
      expect.stringContaining("gates"),
    ]);
    expect(items[0].textContent).toContain("0.71");

    fireEvent.click(items[0]);
    const article = await screen.findByRole("article", { name: "logic" });
    expect(article.querySelector("mark")?.textContent).toBe("# Logic\n\nUse a Karnaugh map.");
  });

  it("shows a load error when the note can no longer be opened", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.endsWith("/api/search/semantic")
          ? json(searchResponse("q", [hit("gone.md", 0.5, "x")]))
          : json({ detail: { code: "note_not_found", message: "gone.md does not exist" } }, 404),
      ),
    );
    render(<App />);
    search("q");
    fireEvent.click(await screen.findByRole("button", { name: /gone/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("gone.md does not exist");
  });
});

describe("SemanticSearchPanel", () => {
  it("distinguishes no matches from an infrastructure error", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(json(searchResponse("nothing", [])))
      .mockResolvedValueOnce(json({ detail: { code: "index_unavailable", message: "the index is still loading" } }, 503));
    vi.stubGlobal("fetch", fetchMock);
    render(<SemanticSearchPanel onOpen={() => undefined} />);

    search("nothing");
    expect(await screen.findByText(/No notes match/)).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();

    search("again");
    expect((await screen.findByRole("alert")).textContent).toContain("the index is still loading");
  });

  it("reports an unreachable API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<SemanticSearchPanel onOpen={() => undefined} />);
    search("logic");
    expect((await screen.findByRole("alert")).textContent).toContain("not reachable");
  });

  it("does not search for a blank query", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<SemanticSearchPanel onOpen={() => undefined} />);
    search("   ");
    expect(fetchMock).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Search" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("keeps the newest results when an older request finishes last", async () => {
    let resolveOld: (response: Response) => void = () => undefined;
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => new Promise<Response>((resolve) => (resolveOld = resolve)))
      .mockResolvedValueOnce(json(searchResponse("new", [hit("new.md", 0.9, "new")])));
    vi.stubGlobal("fetch", fetchMock);
    render(<SemanticSearchPanel onOpen={() => undefined} />);

    search("old");
    search("new");
    await screen.findByRole("button", { name: /new/ });
    resolveOld(json(searchResponse("old", [hit("old.md", 0.9, "old")])));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("button", { name: /old/ })).toBeNull();
    expect(screen.getByRole("button", { name: /new/ })).toBeTruthy();
  });

  it("opens a result with the keyboard-focusable button", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(searchResponse("q", [hit("a.md", 0.3, "A")]))));
    const onOpen = vi.fn();
    render(<SemanticSearchPanel onOpen={onOpen} />);
    search("q");
    const button = await screen.findByRole("button", { name: /a\.md/ });
    button.focus();
    expect(document.activeElement).toBe(button);
    fireEvent.click(button);
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ path: "a.md" }));
  });
});

describe("byteRangeToCharRange", () => {
  it("maps UTF-8 byte offsets to string offsets", () => {
    expect(byteRangeToCharRange("é☕a🎉b", 2, 6)).toEqual([1, 3]);
    expect(byteRangeToCharRange("é☕a🎉b", 6, 10)).toEqual([3, 5]);
  });
});
