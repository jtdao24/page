import type { Backlink } from "../types";

interface BacklinksPanelProps {
  backlinks: Backlink[];
  onOpen: (noteId: string) => void;
}

export default function BacklinksPanel({ backlinks, onOpen }: BacklinksPanelProps) {
  return (
    <aside className="flex h-full min-h-0 w-64 shrink-0 flex-col border-l border-neutral-200 bg-neutral-50">
      <div className="border-b border-neutral-200 px-3 py-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">Backlinks</h2>
      </div>
      {backlinks.length === 0 ? (
        <p className="px-3 py-3 text-sm text-neutral-500">No notes link here yet.</p>
      ) : (
        <ul className="min-h-0 flex-1 overflow-auto py-1">
          {backlinks.map((item) => (
            <li key={item.source_id}>
              <button
                type="button"
                onClick={() => onOpen(item.source_id)}
                className="block w-full px-3 py-2 text-left hover:bg-neutral-200"
              >
                <span className="block truncate text-sm font-medium text-neutral-900">
                  {item.source_title}
                </span>
                <span className="mt-0.5 block line-clamp-2 text-xs text-neutral-500">{item.excerpt}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
