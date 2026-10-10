import { useCallback, useEffect, useRef, useState } from "react";
import {
  createNote,
  deleteNote,
  getBacklinks,
  getGraph,
  getNote,
  health,
  listNotes,
  updateNote,
} from "./api";
import BacklinksPanel from "./components/BacklinksPanel";
import KnowledgeGraph from "./components/KnowledgeGraph";
import NoteEditor from "./components/NoteEditor";
import NoteList from "./components/NoteList";
import type { Backlink, GraphData, Note, NoteSummary } from "./types";

const emptyGraph: GraphData = { nodes: [], edges: [] };

export default function App() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState<NoteSummary[]>([]);
  const [active, setActive] = useState<Note | null>(null);
  const [backlinks, setBacklinks] = useState<Backlink[]>([]);
  const [graph, setGraph] = useState<GraphData>(emptyGraph);
  const saveTimer = useRef<number | null>(null);
  const activeRef = useRef<Note | null>(null);
  const persistRef = useRef<(noteId: string, content: string) => Promise<void>>(
    async () => undefined,
  );
  const activeId = active?.id ?? null;
  activeRef.current = active;

  const refreshGraph = useCallback(async () => {
    setGraph(await getGraph());
  }, []);

  const openNote = useCallback(async (id: string) => {
    if (saveTimer.current !== null && activeRef.current) {
      window.clearTimeout(saveTimer.current);
      saveTimer.current = null;
      await persistRef.current(activeRef.current.id, activeRef.current.content);
    }
    const note = await getNote(id);
    setActive(note);
    setBacklinks(await getBacklinks(id));
  }, []);

  const reloadNotes = useCallback(async (preferredId?: string | null) => {
    const listed = await listNotes();
    setNotes(listed);
    const nextId = preferredId && listed.some((note) => note.id === preferredId) ? preferredId : listed[0]?.id;
    if (nextId) {
      await openNote(nextId);
    } else {
      setActive(null);
      setBacklinks([]);
    }
    await refreshGraph();
  }, [openNote, refreshGraph]);

  useEffect(() => {
    let cancelled = false;
    const connect = async () => {
      for (let attempt = 0; attempt < 40; attempt += 1) {
        try {
          await health();
          if (!cancelled) {
            setReady(true);
            await reloadNotes();
          }
          return;
        } catch {
          await new Promise((resolve) => window.setTimeout(resolve, 250));
        }
      }
      if (!cancelled) {
        setError("Page Core API is not running. Start it with python -m page_core.");
      }
    };
    void connect();
    return () => {
      cancelled = true;
    };
  }, [reloadNotes]);

  const persist = useCallback(
    async (noteId: string, content: string) => {
      const saved = await updateNote(noteId, content);
      if (saved.id === noteId) {
        setBacklinks(await getBacklinks(noteId));
      }
      setNotes(await listNotes());
      await refreshGraph();
    },
    [refreshGraph],
  );
  persistRef.current = persist;

  const handleChange = (content: string) => {
    if (!active) {
      return;
    }
    const noteId = active.id;
    setActive({ ...active, content });
    if (saveTimer.current !== null) {
      window.clearTimeout(saveTimer.current);
    }
    saveTimer.current = window.setTimeout(() => {
      void persist(noteId, content).catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to save note.");
      });
    }, 400);
  };

  const handleCreate = async () => {
    const created = await createNote("Untitled", "");
    await reloadNotes(created.id);
  };

  const handleDelete = async () => {
    if (!active) {
      return;
    }
    await deleteNote(active.id);
    await reloadNotes(null);
  };

  if (error && !ready) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-white text-neutral-700">
        <p className="max-w-md px-6 text-center text-sm">{error}</p>
      </main>
    );
  }

  if (!ready) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-white text-neutral-500">
        <p className="text-sm">Connecting to Page Core…</p>
      </main>
    );
  }

  return (
    <main className="flex h-screen flex-col bg-white text-neutral-900">
      <header className="flex items-center justify-between border-b border-neutral-200 px-4 py-2">
        <h1 className="text-sm font-semibold tracking-tight">Page</h1>
        {error ? <p className="text-xs text-rose-700">{error}</p> : null}
      </header>
      <div className="flex min-h-0 flex-1">
        <NoteList
          notes={notes}
          activeId={activeId}
          onSelect={(id) => void openNote(id)}
          onCreate={() => void handleCreate()}
          onDelete={() => void handleDelete()}
        />
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          {active ? (
            <>
              <div className="border-b border-neutral-200 px-4 py-2">
                <h2 className="truncate text-sm font-medium">{active.title}</h2>
              </div>
              <div className="min-h-0 flex-1">
                <NoteEditor
                  note={active}
                  notes={notes}
                  onChange={handleChange}
                  onOpenNote={(id) => void openNote(id)}
                />
              </div>
            </>
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-neutral-500">
              Create a note to start writing.
            </div>
          )}
        </section>
        <BacklinksPanel backlinks={backlinks} onOpen={(id) => void openNote(id)} />
      </div>
      <KnowledgeGraph data={graph} activeId={activeId} onOpenNote={(id) => void openNote(id)} />
    </main>
  );
}
