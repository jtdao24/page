import type { NoteSummary } from "../types";

interface NoteListProps {
  notes: NoteSummary[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onDelete: () => void;
}

export default function NoteList({ notes, activeId, onSelect, onCreate, onDelete }: NoteListProps) {
  return (
    <aside className="flex h-full min-h-0 w-56 shrink-0 flex-col border-r border-neutral-200 bg-neutral-50">
      <div className="flex items-center justify-between gap-2 border-b border-neutral-200 px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Notes</h2>
        <button
          type="button"
          onClick={onCreate}
          className="rounded px-2 py-1 text-xs font-medium text-neutral-800 hover:bg-neutral-200"
        >
          New
        </button>
      </div>
      <ul className="min-h-0 flex-1 overflow-auto py-1">
        {notes.length === 0 ? (
          <li className="px-3 py-2 text-sm text-neutral-500">No notes yet.</li>
        ) : (
          notes.map((note) => (
            <li key={note.id}>
              <button
                type="button"
                onClick={() => onSelect(note.id)}
                className={`block w-full truncate px-3 py-1.5 text-left text-sm ${
                  note.id === activeId
                    ? "bg-neutral-900 text-white"
                    : "text-neutral-800 hover:bg-neutral-200"
                }`}
              >
                {note.title}
              </button>
            </li>
          ))
        )}
      </ul>
      <div className="border-t border-neutral-200 p-2">
        <button
          type="button"
          onClick={onDelete}
          disabled={!activeId}
          className="w-full rounded px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-200 disabled:opacity-40"
        >
          Delete note
        </button>
      </div>
    </aside>
  );
}
