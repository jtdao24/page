import { useEffect, useRef } from "react";
import type { NoteResponse } from "../api/types";
import { byteRangeToCharRange } from "../byteRange";

interface NoteViewProps {
  note: NoteResponse;
  /** UTF-8 byte range of the passage to highlight. */
  highlight?: { start_byte: number; end_byte: number } | null;
}

export default function NoteView({ note, highlight = null }: NoteViewProps) {
  const markRef = useRef<HTMLElement>(null);

  useEffect(() => {
    markRef.current?.scrollIntoView?.({ block: "center" });
  }, [note, highlight]);

  let body = <>{note.content}</>;
  if (highlight) {
    const [from, to] = byteRangeToCharRange(note.content, highlight.start_byte, highlight.end_byte);
    body = (
      <>
        {note.content.slice(0, from)}
        <mark ref={markRef} className="rounded bg-amber-100 text-inherit">
          {note.content.slice(from, to)}
        </mark>
        {note.content.slice(to)}
      </>
    );
  }

  return (
    <article aria-label={note.title} className="flex h-full min-h-0 flex-col">
      <header className="border-b border-neutral-200 px-4 py-2">
        <h2 className="truncate text-sm font-semibold">{note.title}</h2>
        <p className="truncate text-xs text-neutral-500">{note.path}</p>
      </header>
      <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words px-4 py-3 font-sans text-sm leading-relaxed text-neutral-900">
        {body}
      </pre>
    </article>
  );
}
