import { useRef, useState } from "react";
import { ApiError, getNote } from "./api/client";
import type { NoteResponse, SemanticSearchHit } from "./api/types";
import NoteView from "./components/NoteView";
import SemanticSearchPanel from "./components/SemanticSearchPanel";

type OpenNote =
  | { kind: "none" }
  | { kind: "loading"; path: string }
  | { kind: "open"; note: NoteResponse; hit: SemanticSearchHit }
  | { kind: "error"; path: string; message: string };

function App() {
  const [open, setOpen] = useState<OpenNote>({ kind: "none" });
  const latest = useRef(0);

  const openHit = async (hit: SemanticSearchHit) => {
    const id = ++latest.current;
    setOpen({ kind: "loading", path: hit.path });
    try {
      const note = await getNote(hit.path);
      if (id === latest.current) {
        setOpen({ kind: "open", note, hit });
      }
    } catch (error) {
      if (id === latest.current) {
        const message = error instanceof ApiError ? error.message : "The note could not be opened.";
        setOpen({ kind: "error", path: hit.path, message });
      }
    }
  };

  const activePath = open.kind === "none" ? null : open.kind === "open" ? open.note.path : open.path;

  return (
    <main className="flex h-screen flex-col bg-white text-neutral-900">
      <header className="border-b border-neutral-200 px-4 py-2">
        <h1 className="text-sm font-semibold tracking-tight">Page</h1>
      </header>
      <div className="flex min-h-0 flex-1">
        <aside className="w-96 shrink-0 border-r border-neutral-200 bg-neutral-50">
          <SemanticSearchPanel onOpen={(hit) => void openHit(hit)} activePath={activePath} />
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
    </main>
  );
}

export default App;
