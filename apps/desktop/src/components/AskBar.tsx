import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { type AskResponse, type DesktopError, type GeminiKeyStatus, toDesktopError } from "../core/types";
import { backendReady, navigationBlocked, type WorkspaceController, type WorkspaceState } from "../workspace/controller";
import { ErrorText } from "./ErrorText";
import { Icon } from "./Icon";

const BUDGETS = [500, 1500, 4000] as const;
const INPUT_ID = "ask-question";

/** Focus the floating ask box (Cmd/Ctrl+K and the sidebar's Ask item). */
export function focusAskBar() {
  document.getElementById(INPUT_ID)?.focus();
}

interface Exchange {
  id: number;
  question: string;
  response?: AskResponse;
  error?: DesktopError;
}

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
      <label htmlFor="gemini-key" className="sr-only">Gemini API key</label>
      <input id="gemini-key" type="password" autoComplete="off" spellCheck={false} value={key} placeholder="Paste API key"
        onChange={(event) => setKey(event.target.value)} />
      <button type="submit" disabled={busy || !canRestart || !key.trim()}>Save Key</button>
      {status?.stored && <button type="button" disabled={busy || !canRestart} onClick={() => void apply(null)}>Remove Key</button>}
    </form>
    {notice?.message && <p role="status" className="knowledge-hint">{notice.message}</p>}
    {notice?.error && <div role="alert"><ErrorText error={notice.error} /></div>}
  </div>;
}

function Answer({ response, blocked, controller }: { response: AskResponse; blocked: boolean; controller: WorkspaceController }) {
  const sources = new Map(response.sources.map((source) => [source.number, source]));
  return <>
    <div className="ask-answer" aria-label="Answer">
      {response.answer.split(/(\[\d+\])/).map((part, index) => {
        const match = /^\[(\d+)\]$/.exec(part);
        const source = match ? sources.get(Number(match[1])) : undefined;
        return source
          ? <button key={index} className="citation" disabled={blocked} title={source.relative_path}
              onClick={() => void controller.selectNote(source.note_id)}>{source.number}</button>
          : <span key={index}>{part}</span>;
      })}
    </div>
    {response.sources.length > 0 && <details className="ask-sources">
      <summary>{response.sources.length} {response.sources.length === 1 ? "source" : "sources"}</summary>
      <ol>{response.sources.map((source) =>
        <li key={source.number} className={response.cited.includes(source.number) ? "cited" : undefined}>
          <button disabled={blocked} onClick={() => void controller.selectNote(source.note_id)}>
            <span className="source-number">{source.number}</span>{source.relative_path}
          </button>
          <small>Lines {source.start_line}–{source.end_line}{source.excerpt ? " · excerpt" : ""}
            {response.cited.includes(source.number) ? " · cited" : ""}</small>
          <p>{source.text}</p>
        </li>)}</ol>
    </details>}
    <p className="ask-usage">
      {response.answered_by_model
        ? `Context ${response.usage.context_tokens.toLocaleString()} of ${response.usage.budget.toLocaleString()} tokens · `
          + `${response.model}: ${response.usage.input_tokens.toLocaleString()} in, ${response.usage.output_tokens.toLocaleString()} out`
        : "No relevant passages were found, so Gemini was not called."}
    </p>
  </>;
}

/** A floating ask box over the note; answers stack in a card above it. */
export function AskBar({ controller, state }: { controller: WorkspaceController; state: WorkspaceState }) {
  const [question, setQuestion] = useState("");
  const [budget, setBudget] = useState<number>(1500);
  const [thread, setThread] = useState<{ vaultId: string | undefined; exchanges: Exchange[] }>({ vaultId: undefined, exchanges: [] });
  const [loading, setLoading] = useState<{ key: string; request: number } | null>(null);
  const [cardOpen, setCardOpen] = useState(false);
  const [keyVisible, setKeyVisible] = useState(false);
  const owner = useRef(0);
  const nextId = useRef(0);
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const available = backendReady(state) && !state.vaultBusy && !state.pending && !state.recovery && !state.unknown;
  // Answers in flight belong to one vault and running Core process: they are
  // dropped if either changes or Core stops. Another vault starts a new thread.
  const key = JSON.stringify([state.vault?.id, state.backend?.generation, backendReady(state)]);
  useEffect(() => {
    const ownership = owner;
    ownership.current++;
    return () => {
      ownership.current++;
      // A request from before the change can no longer finish, so stop showing it as busy.
      setLoading(null);
    };
  }, [key]);
  const vaultId = state.vault?.id;
  const exchanges = thread.vaultId === vaultId ? thread.exchanges : [];
  const busy = loading?.key === key;
  const blocked = navigationBlocked(state) || state.recovery !== null;
  const lastError = exchanges.at(-1)?.error;
  const showKey = keyVisible || lastError?.code === "llm_not_configured";

  useEffect(() => {
    const field = input.current;
    if (!field) return;
    field.style.height = "auto";
    field.style.height = `${Math.min(field.scrollHeight, 140)}px`;
  }, [question]);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "end", behavior: "smooth" }); }, [exchanges.length, busy]);

  /** Ask the typed question, or retry an earlier one without touching what's typed. */
  async function ask(retry?: string) {
    const text = retry ?? question.trim();
    if (!vaultId || !available || busy || !text) return;
    const request = ++owner.current;
    const id = ++nextId.current;
    setLoading({ key, request });
    setCardOpen(true);
    if (retry === undefined) setQuestion("");
    setThread((current) => ({ vaultId, exchanges: [...(current.vaultId === vaultId ? current.exchanges : []), { id, question: text }] }));
    const settle = (patch: Partial<Exchange>) => {
      if (owner.current !== request) return;
      setThread((current) => ({ ...current, exchanges: current.exchanges.map((item) => item.id === id ? { ...item, ...patch } : item) }));
    };
    try {
      settle({ response: await controller.askVault(vaultId, text, budget) });
    } catch (cause: unknown) {
      settle({ error: toDesktopError(cause) });
    } finally {
      setLoading((current) => (current?.request === request ? null : current));
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void ask();
    }
    if (event.key === "Escape") { setCardOpen(false); input.current?.blur(); }
  }

  const hasCard = cardOpen && (exchanges.length > 0 || showKey);
  return <div className="ask-dock">
    {hasCard && <section className="ask-card" aria-label="Answers">
      <header className="ask-card-header">
        <span><Icon name="sparkle" size={14} />Ask your notes</span>
        <button className="icon-button" aria-label="New conversation" title="New conversation" disabled={busy || exchanges.length === 0}
          onClick={() => setThread({ vaultId, exchanges: [] })}><Icon name="plus" size={14} /></button>
        <button className="icon-button" aria-label="Close answers" title="Close (Esc)" onClick={() => setCardOpen(false)}><Icon name="minimize" size={14} /></button>
      </header>
      <div className="ask-thread">
        <p className="ask-privacy">Answers use only your saved notes. The passages picked for each question, not your whole vault, are sent to Google Gemini.</p>
        {showKey && <GeminiKey controller={controller} canRestart={!state.pending && !state.vaultBusy && !state.quitting} />}
        {exchanges.map((exchange) => <article key={exchange.id} className="ask-exchange">
          <p className="ask-question">{exchange.question}</p>
          {exchange.response && <Answer response={exchange.response} blocked={blocked} controller={controller} />}
          {!exchange.response && !exchange.error && (busy && exchange === exchanges.at(-1)
            ? <p role="status" className="ask-thinking"><span className="dots" aria-hidden="true"><i /><i /><i /></span>Finding passages and asking Gemini…</p>
            : <p className="knowledge-hint">This answer was interrupted when Page Core restarted.</p>)}
          {exchange.error && <div role="alert" className="ask-error">
            {exchange.error.code === "llm_not_configured"
              ? <p>Ask needs a Gemini API key. Add one above.</p>
              : <ErrorText error={exchange.error} />}
            {exchange.error.code !== "llm_not_configured" && exchange === exchanges.at(-1) &&
              <button disabled={!available || busy} onClick={() => void ask(exchange.question)}>Try Again</button>}
          </div>}
        </article>)}
        <div ref={end} />
      </div>
    </section>}
    <form className="ask-box" aria-label="Ask your notes" onSubmit={(event) => { event.preventDefault(); void ask(); }}>
      <label htmlFor={INPUT_ID} className="sr-only">Question</label>
      <textarea ref={input} id={INPUT_ID} rows={1} value={question} maxLength={2000} disabled={!state.vault}
        placeholder={available ? "Ask your notes…" : "Asking is available when Core and the vault are ready"}
        onChange={(event) => setQuestion(event.target.value)} onKeyDown={onKeyDown}
        onFocus={() => { if (exchanges.length > 0) setCardOpen(true); }} />
      <div className="ask-controls">
        <label htmlFor="ask-budget" className="sr-only">Context budget</label>
        <select id="ask-budget" value={budget} title="Context budget" onChange={(event) => setBudget(Number(event.target.value))}>
          {BUDGETS.map((value) => <option key={value} value={value}>{value.toLocaleString()} tokens</option>)}
        </select>
        <button type="button" className="icon-button" aria-label="Gemini API key" title="Gemini API key" aria-pressed={showKey}
          onClick={() => { setKeyVisible(!keyVisible); setCardOpen(true); }}><Icon name="key" size={15} /></button>
        <button type="submit" className="ask-send" aria-label="Ask" disabled={!available || busy || !question.trim()}><Icon name="send" size={16} /></button>
      </div>
    </form>
  </div>;
}
