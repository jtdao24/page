import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView, highlightActiveLine, keymap, lineNumbers } from "@codemirror/view";
import { useEffect, useRef } from "react";
import type { Note, NoteSummary } from "../types";
import { wikiLinkExtension } from "../wikiLinkExtension";

interface NoteEditorProps {
  note: Note;
  notes: NoteSummary[];
  onChange: (content: string) => void;
  onOpenNote: (noteId: string) => void;
}

export default function NoteEditor({ note, notes, onChange, onOpenNote }: NoteEditorProps) {
  const parentRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const wikiCompartmentRef = useRef(new Compartment());
  const noteIdRef = useRef(note.id);
  const onChangeRef = useRef(onChange);
  const onOpenNoteRef = useRef(onOpenNote);
  const notesRef = useRef(notes);

  onChangeRef.current = onChange;
  onOpenNoteRef.current = onOpenNote;
  notesRef.current = notes;

  useEffect(() => {
    if (!parentRef.current) {
      return;
    }
    wikiCompartmentRef.current = new Compartment();
    const view = new EditorView({
      state: EditorState.create({
        doc: note.content,
        extensions: [
          lineNumbers(),
          highlightActiveLine(),
          history(),
          markdown(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          wikiCompartmentRef.current.of(
            wikiLinkExtension(notesRef.current, (id) => onOpenNoteRef.current(id)),
          ),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) {
              onChangeRef.current(update.state.doc.toString());
            }
          }),
          EditorView.theme({
            "&": {
              height: "100%",
              fontSize: "14px",
            },
            ".cm-scroller": {
              fontFamily: "ui-sans-serif, system-ui, sans-serif",
            },
            ".cm-content": {
              padding: "12px 0",
            },
          }),
        ],
      }),
      parent: parentRef.current,
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
    // Recreate when the open note changes so wiki-link decorations use current notes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [note.id]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) {
      return;
    }
    view.dispatch({
      effects: wikiCompartmentRef.current.reconfigure(
        wikiLinkExtension(notes, (id) => onOpenNoteRef.current(id)),
      ),
    });
  }, [notes]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) {
      return;
    }
    if (noteIdRef.current !== note.id) {
      noteIdRef.current = note.id;
      return;
    }
    const current = view.state.doc.toString();
    if (current !== note.content) {
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: note.content },
      });
    }
  }, [note.id, note.content]);

  return <div ref={parentRef} className="h-full min-h-0 overflow-hidden bg-white" />;
}
