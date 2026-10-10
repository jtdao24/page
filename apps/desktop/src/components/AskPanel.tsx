import { useEffect, useRef, useState } from "react";
import { type AskResponse, type DesktopError, type GeminiKeyStatus, toDesktopError } from "../core/types";
import { backendReady, navigationBlocked, type WorkspaceController, type WorkspaceState } from "../workspace/controller";
import { ErrorText } from "./ErrorText";

const BUDGETS = [500, 1500, 4000] as const;

/** The Gemini key, saved in the system credential store; saving restarts Core. */
function GeminiKey({ controller, canRestart }: { controller: WorkspaceController; canRestart: boolean }) {
  const [status, setStatus] = useState<GeminiKeyStatus | null>(null);
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ message?: string; error?: DesktopError } | null>(null);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    controller.geminiKeyStatus().then(
      (value) => { if (live.current) setStatus(value); },
      (cause: unknown) => { if (live.current) setNotice({ error: toDesktopError(cause) }); });
    return () => { live.current = false; };
  }, [controller]);

  async function apply(value: string | null) {
    setBusy(true);
    setNotice(null);
    try {
      await controller.setGeminiKey(value);
      const next = await controller.geminiKeyStatus();
      if (!live.current) return;
      setKey("");
      setStatus(next);
      setNotice({ message: value === null ? "Key removed." : "Key saved. Page Core restarted to use it." });
    } catch (cause: unknown) {
      if (live.current) setNotice({ error: toDesktopError(cause) });
    } finally {
      if (live.current) setBusy(false);
    }
  }

  return <div className="ask-key" aria-label="Gemini API key">
    <p className="knowledge-hint">
      {status === null ? "Checking for a Gemini API key…"
        : status.stored ? "A Gemini API key is saved in your system keychain."
        : status.from_environment ? "Using GEMINI_API_KEY from the environment Page started in."
        : "No Gemini API key is set. Create one in Google AI Studio."}
    </p>
    <form onSubmit={(event) => { event.preventDefault(); if (key.trim()) void apply(key); }}>
      <label htmlFor="gemini-key">Gemini API key</label>
      <input id="gemini-key" type="password" autoComplete="off" spellCheck={false} value={key}
        onChange={(event) => setKey(event.target.value)} />
      <button type="submit" disabled={busy || !canRestart || !key.trim()}>Save Key</button>
      {status?.stored && <button type="button" disabled={busy || !canRestart} onClick={() => void apply(null)}>Remove Key</button>}
    </form>
    {notice?.message && <p role="status">{notice.message}</p>}
    {notice?.error && <div role="alert"><ErrorText error={notice.error} /></div>}
  </div>;
}

export function AskPanel({ controller, state, onClose }: {
  controller: WorkspaceController; state: WorkspaceState; onClose: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [budget, setBudget] = useState<number>(1500);
  const [keyVisible, setKeyVisible] = useState(false);
  const [busy, setBusy] = useState<{ key: string; request: number } | null>(null);
  const [result, setResult] = useState<{ key: string; response?: AskResponse; error?: DesktopError } | null>(null);
  const owner = useRef(0);
  const available = backendReady(state) && !state.vaultBusy && !state.pending && !state.recovery && !state.unknown;
  // Answers belong to one vault, Core process and set of saved revisions; any change makes them stale.
  const accepted = state.document?.accepted;
  const key = JSON.stringify([state.vault?.id, state.backend?.generation, available,
    state.notes?.map((note) => [note.id, note.id === accepted?.id ? accepted.revision : note.revision])]);
  useEffect(() => {
    const ownership = owner;
    ownership.current++;
    return () => { ownership.current++; };
  }, [key]);
  const visible = result?.key === key ? result : null;
  const loading = busy?.key === key;
  const blocked = navigationBlocked(state) || state.recovery !== null;

  async function ask() {
    const vaultId = state.vault?.id;
    const text = question.trim();
    if (!vaultId || !available || loading || !text) return;
    const request = ++owner.current;
    setBusy({ key, request });
    setResult(null);
    try {
      const response = await controller.askVault(vaultId, text, budget);
      if (owner.current === request) setResult({ key, response });
    } catch (cause: unknown) {
      if (owner.current === request) setResult({ key, error: toDesktopError(cause) });
    } finally {
      setBusy((current) => (current?.request === request ? null : current));
    }
  }

  const response = visible?.response;
  const showKey = keyVisible || visible?.error?.code === "llm_not_configured";
  const sources = new Map(response?.sources.map((source) => [source.number, source]) ?? []);

  return <aside className="knowledge-panel ask-panel" aria-label="Ask your notes">
    <header className="knowledge-heading"><h2>Ask your notes</h2><button aria-label="Close ask" onClick={onClose}>×</button></header>
    <button type="button" className="ask-key-toggle" aria-expanded={showKey} onClick={() => setKeyVisible(!keyVisible)}>
      Gemini API key
    </button>
    {showKey && <GeminiKey controller={controller} canRestart={!state.pending && !state.vaultBusy && !state.quitting} />}
    <p className="knowledge-hint">
      Answers use only your saved notes. The passages selected for a question, not your whole vault,
      are sent to Google Gemini. Unsaved drafts are excluded.
    </p>
    <form onSubmit={(event) => { event.preventDefault(); void ask(); }}>
      <label htmlFor="ask-question">Question</label>
      <textarea id="ask-question" value={question} maxLength={2000} rows={3}
        placeholder="What would you like to know?" onChange={(event) => setQuestion(event.target.value)} />
      <label htmlFor="ask-budget">Context budget</label>
      <select id="ask-budget" value={budget} onChange={(event) => setBudget(Number(event.target.value))}>
        {BUDGETS.map((value) => <option key={value} value={value}>{value.toLocaleString()} tokens</option>)}
      </select>
      <button disabled={!available || loading || !question.trim()} type="submit">Ask</button>
    </form>
    {!available && <p role="status">Asking is available when Core and the vault are ready.</p>}
    {loading && <p role="status">Finding relevant passages and asking Gemini…</p>}
    {visible?.error && <div role="alert">
      {visible.error.code === "llm_not_configured"
        ? <p>Ask needs a Gemini API key. Add one under Gemini API key above.</p>
        : <ErrorText error={visible.error} />}
      {visible.error.code !== "llm_not_configured" &&
        <button disabled={!available || loading} onClick={() => void ask()}>Try Again</button>}
    </div>}
    {response && <>
      <div className="ask-answer" aria-label="Answer">
        {response.answer.split(/(\[\d+\])/).map((part, index) => {
          const match = /^\[(\d+)\]$/.exec(part);
          const source = match ? sources.get(Number(match[1])) : undefined;
          return source
            ? <button key={index} className="citation" disabled={blocked} title={source.relative_path}
                onClick={() => void controller.selectNote(source.note_id)}>[{source.number}]</button>
            : <span key={index}>{part}</span>;
        })}
      </div>
      <p className="ask-usage" role="status">
        {response.answered_by_model
          ? `Context ${response.usage.context_tokens.toLocaleString()} of ${response.usage.budget.toLocaleString()} tokens · `
            + `${response.model}: ${response.usage.input_tokens.toLocaleString()} in, ${response.usage.output_tokens.toLocaleString()} out`
          : "No relevant passages were found, so Gemini was not called."}
      </p>
      {response.sources.length > 0 && <ol className="search-results ask-sources">{response.sources.map((source) =>
        <li key={source.number} className={response.cited.includes(source.number) ? "cited" : undefined}>
          <button disabled={blocked} onClick={() => void controller.selectNote(source.note_id)}>
            [{source.number}] {source.relative_path}
          </button>
          <small>Lines {source.start_line}–{source.end_line}{source.excerpt ? " · excerpt" : ""}
            {response.cited.includes(source.number) ? " · cited" : ""}</small>
          <p>{source.text}</p>
        </li>)}</ol>}
    </>}
  </aside>;
}
