import { useEffect, useRef, useState } from "react";
import { type DesktopError, type SearchResponse, toDesktopError } from "../core/types";
import { backendReady, navigationBlocked, type WorkspaceController, type WorkspaceState } from "../workspace/controller";
import { ErrorText } from "./ErrorText";

export function SemanticSearch({ controller, state, onClose }: {
  controller: WorkspaceController; state: WorkspaceState; onClose: () => void;
}) {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<{ key: string; response?: SearchResponse; error?: DesktopError; message?: string } | null>(null);
  const owner = useRef(0);
  const available = backendReady(state) && !state.vaultBusy && !state.pending && !state.recovery && !state.unknown;
  const accepted = state.document?.accepted;
  const key = JSON.stringify([state.vault?.id, state.backend?.generation, available,
    state.notes?.map((note) => [note.id, note.id === accepted?.id ? accepted.revision : note.revision])]);
  useEffect(() => {
    const ownership = owner;
    ownership.current++;
    return () => { ownership.current++; };
  }, [key]);
  const visible = result?.key === key ? result : null;
  const loading = busy === key;
  const blocked = navigationBlocked(state) || state.recovery !== null;

  async function run(rebuild = false) {
    const vaultId = state.vault?.id;
    if (!vaultId || !available || loading || (!rebuild && !query.trim())) return;
    const request = ++owner.current;
    setBusy(key);
    setResult(null);
    try {
      if (rebuild) {
        const report = await controller.indexVault(vaultId, true);
        if (owner.current === request) setResult({ key, message: `Index rebuilt: ${report.chunks} chunks from ${report.notes} notes.` });
      } else {
        const response = await controller.searchVault(vaultId, query.trim());
        if (owner.current === request) setResult({ key, response });
      }
    } catch (cause: unknown) {
      if (owner.current === request) setResult({ key, error: toDesktopError(cause) });
    } finally {
      if (owner.current === request) setBusy(null);
    }
  }

  return <aside className="knowledge-panel search-panel" aria-label="Semantic search">
    <header className="knowledge-heading"><h2>Search by meaning</h2><button aria-label="Close search" onClick={onClose}>×</button></header>
    <p className="knowledge-hint">Search saved Markdown locally. Unsaved drafts are excluded.</p>
    <form onSubmit={(event) => { event.preventDefault(); void run(); }}>
      <label htmlFor="semantic-query">Find in your vault</label>
      <input id="semantic-query" value={query} maxLength={2000} placeholder="What would you like to find?"
        onChange={(event) => setQuery(event.target.value)} />
      <button disabled={!available || loading || !query.trim()} type="submit">Search Notes</button>
    </form>
    {!available && <p role="status">Search is available when Core and the vault are ready.</p>}
    {loading && <p role="status">Indexing saved notes and searching…</p>}
    {visible?.error && <div role="alert"><ErrorText error={visible.error} />
      {visible.error.code === "model_unavailable" && <p>Install the local search model once using the setup instructions in the project documentation.</p>}
      <button disabled={!available || loading} onClick={() => void run(visible.error?.code === "index_corrupt")}>{visible.error.code === "index_corrupt" ? "Rebuild Index" : "Retry Search"}</button>
    </div>}
    {visible?.message && <p role="status">{visible.message}</p>}
    {visible?.response && <>
      <p role="status">{visible.response.hits.length} matching passages · similarity ranking</p>
      {visible.response.hits.length === 0 && <p>No saved passages to search yet.</p>}
      <ol className="search-results">{visible.response.hits.map((hit) => <li key={hit.chunk_id}>
        <button disabled={blocked} onClick={() => void controller.selectNote(hit.note_id)}>{hit.relative_path}</button>
        <small>Lines {hit.start_line}–{hit.end_line} · {hit.score.toFixed(3)}</small>
        <p>{hit.text}</p>
      </li>)}</ol>
    </>}
  </aside>;
}
