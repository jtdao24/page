import { useRef, useState } from "react";
import { ApiError, getNote, isUnauthorized, setApiToken } from "./api/client";
import type { NoteResponse, SemanticSearchHit } from "./api/types";
import ConnectForm from "./components/ConnectForm";
import NoteView from "./components/NoteView";
import SemanticSearchPanel from "./components/SemanticSearchPanel";

// The token is remembered only for this window's session, never on disk.
const TOKEN_KEY = "page.apiToken";

type OpenNote =
  | { kind: "none" }
  | { kind: "loading"; path: string }
  | { kind: "open"; note: NoteResponse; hit: SemanticSearchHit }
  | { kind: "error"; path: string; message: string };

type Connection = { kind: "connected" } | { kind: "disconnected"; notice: string | null };

function readStoredToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeToken(token: string | null): void {
  try {
    if (token) {
      sessionStorage.setItem(TOKEN_KEY, token);
    } else {
      sessionStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // Storage can be unavailable; the token then lasts until the page reloads.
  }
}

function App() {
  const [connection, setConnection] = useState<Connection>(() => {
    const stored = readStoredToken();
    setApiToken(stored);
    return stored ? { kind: "connected" } : { kind: "disconnected", notice: null };
  });
  const [open, setOpen] = useState<OpenNote>({ kind: "none" });
  const latest = useRef(0);

  const disconnect = (notice: string | null) => {
    latest.current += 1;
    setApiToken(null);
    storeToken(null);
    setOpen({ kind: "none" });
    setConnection({ kind: "disconnected", notice });
  };

  const tokenRejected = () =>
    disconnect("Page Core did not accept the saved token. It may have restarted; paste its new token.");

  const openHit = async (hit: SemanticSearchHit) => {
    const id = ++latest.current;
    setOpen({ kind: "loading", path: hit.path });
    try {
      const note = await getNote(hit.path);
      if (id === latest.current) {
        setOpen({ kind: "open", note, hit });
      }
    } catch (error) {
      if (id !== latest.current) {
        return;
      }
      if (isUnauthorized(error)) {
        tokenRejected();
        return;
      }
      const message = error instanceof ApiError ? error.message : "The note could not be opened.";
      setOpen({ kind: "error", path: hit.path, message });
    }
  };

  const activePath = open.kind === "none" ? null : open.kind === "open" ? open.note.path : open.path;

  return (
    <main className="flex h-screen flex-col bg-white text-neutral-900">
      <header className="flex items-center justify-between border-b border-neutral-200 px-4 py-2">
        <h1 className="text-sm font-semibold tracking-tight">Page</h1>
        {connection.kind === "connected" && (
          <button
            type="button"
            onClick={() => disconnect(null)}
            className="rounded px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-100 focus-visible:outline-2 focus-visible:outline-neutral-900"
          >
            Disconnect
          </button>
        )}
      </header>
      {connection.kind === "disconnected" ? (
        <ConnectForm
          notice={connection.notice}
          onConnected={(token) => {
            storeToken(token);
            setConnection({ kind: "connected" });
          }}
        />
      ) : (
        <div className="flex min-h-0 flex-1">
          <aside className="w-96 shrink-0 border-r border-neutral-200 bg-neutral-50">
            <SemanticSearchPanel
              onOpen={(hit) => void openHit(hit)}
              onUnauthorized={tokenRejected}
              activePath={activePath}
            />
          </aside>
          <section className="min-w-0 flex-1">
            {open.kind === "none" && (
              <p className="p-4 text-sm text-neutral-500">Open a search result to read the note.</p>
            )}
            {open.kind === "loading" && <p className="p-4 text-sm text-neutral-500">Opening {open.path}…</p>}
            {open.kind === "error" && (
              <p role="alert" className="p-4 text-sm text-rose-700">
                Could not open {open.path}: {open.message}
              </p>
            )}
            {open.kind === "open" && <NoteView note={open.note} highlight={open.hit.chunk} />}
          </section>
        </div>
      )}
    </main>
  );
}

export default App;
