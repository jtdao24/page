import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, semanticSearch } from "../api/client";
import type { SemanticSearchHit } from "../api/types";

type SearchState =
  | { kind: "idle" }
  | { kind: "loading"; query: string }
  | { kind: "done"; query: string; results: SemanticSearchHit[] }
  | { kind: "error"; message: string };

interface SemanticSearchPanelProps {
  onOpen: (hit: SemanticSearchHit) => void;
  activePath?: string | null;
  limit?: number;
}

export default function SemanticSearchPanel({ onOpen, activePath = null, limit = 10 }: SemanticSearchPanelProps) {
  const [query, setQuery] = useState("");
  const [state, setState] = useState<SearchState>({ kind: "idle" });
  // Only the latest search may update the results.
  const latest = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const runSearch = async (event: FormEvent) => {
    event.preventDefault();
    const text = query.trim();
    if (!text) {
      return;
    }
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    const id = ++latest.current;
    setState({ kind: "loading", query: text });
    try {
      const response = await semanticSearch(text, limit, abort.signal);
      if (id === latest.current) {
        setState({ kind: "done", query: response.query, results: response.results });
      }
    } catch (error) {
      if (id !== latest.current || (error instanceof DOMException && error.name === "AbortError")) {
        return;
      }
      const message = error instanceof ApiError ? error.message : "Search failed unexpectedly.";
      setState({ kind: "error", message });
    }
  };

  return (
    <section aria-label="Semantic search" className="flex h-full min-h-0 flex-col">
      <form role="search" onSubmit={runSearch} className="flex gap-2 border-b border-neutral-200 p-3">
        <label htmlFor="semantic-query" className="sr-only">
          Search notes by meaning
        </label>
        <input
          id="semantic-query"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Ask about your notes…"
          className="min-w-0 flex-1 rounded border border-neutral-300 px-2 py-1.5 text-sm focus:border-neutral-900 focus:outline-none"
        />
        <button
          type="submit"
          disabled={!query.trim() || state.kind === "loading"}
          className="rounded bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-900 disabled:opacity-40"
        >
          Search
        </button>
      </form>
      <div className="min-h-0 flex-1 overflow-auto" aria-live="polite">
        {state.kind === "idle" && (
          <p className="p-3 text-sm text-neutral-500">Describe what you are looking for in your own words.</p>
        )}
        {state.kind === "loading" && <p className="p-3 text-sm text-neutral-500">Searching…</p>}
        {state.kind === "error" && (
          <p role="alert" className="p-3 text-sm text-rose-700">
            Search is unavailable: {state.message}
          </p>
        )}
        {state.kind === "done" && state.results.length === 0 && (
          <p className="p-3 text-sm text-neutral-500">No notes match “{state.query}”.</p>
        )}
        {state.kind === "done" && state.results.length > 0 && (
          <ol aria-label="Search results" className="py-1">
            {state.results.map((hit) => (
              <li key={hit.note_id}>
                <button
                  type="button"
                  onClick={() => onOpen(hit)}
                  aria-current={hit.path === activePath ? "true" : undefined}
                  className={`block w-full px-3 py-2 text-left focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-neutral-900 ${
                    hit.path === activePath ? "bg-neutral-200" : "hover:bg-neutral-100"
                  }`}
                >
                  <span className="flex items-baseline justify-between gap-2">
                    <span className="truncate text-sm font-medium text-neutral-900">{hit.title}</span>
                    <span
                      className="shrink-0 font-mono text-xs text-neutral-500"
                      title="Cosine similarity of your query and the best-matching passage (higher is closer; not a probability)"
                    >
                      {hit.score.toFixed(2)}
                    </span>
                  </span>
                  <span className="block truncate text-xs text-neutral-500">{hit.path}</span>
                  <span className="mt-1 line-clamp-3 block whitespace-pre-line text-xs text-neutral-700">
                    {hit.excerpt}
                  </span>
                </button>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
