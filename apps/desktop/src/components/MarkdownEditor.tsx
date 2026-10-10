import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown } from "@codemirror/lang-markdown";
import { defaultHighlightStyle, HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { Compartment, EditorState, type Extension, type TransactionSpec } from "@codemirror/state";
import { EditorView, drawSelection, highlightActiveLine, keymap, lineNumbers } from "@codemirror/view";
import { useEffect, useRef } from "react";
import type { LineSeparator } from "../workspace/text";

const syntaxColors: Record<string, string> = {
  "#404740": "#53677a", "#708": "#355d83", "#219": "#294f75",
  "#164": "#426f73", "#a11": "#805443", "#e40": "#8b632f",
  "#00f": "#3d688a", "#30a": "#355d83", "#085": "#426f73",
  "#167": "#446b80", "#256": "#3d688a", "#00c": "#446b80",
};
const bookHighlightStyle = HighlightStyle.define(defaultHighlightStyle.specs.map((spec) => ({
  ...spec, ...(typeof spec.color === "string" ? { color: syntaxColors[spec.color] ?? "#223a50" } : {}),
})));

export interface MarkdownEditorProps {
  /** A new key recreates the editor: new document, empty undo history. */
  documentKey: string;
  initialContent: string;
  /** Serialization separator for uniform documents; null for mixed (read-only) ones. */
  separator: LineSeparator | null;
  readOnly: boolean;
  label: string;
  /** Receives the serialized document after every change. */
  onChange: (content: string) => void;
}

/**
 * Keep inserted text consistent with the document's separator. With a line
 * separator configured, CodeMirror only splits on that string, so pasted
 * text with other line breaks would otherwise leave stray CR/LF characters
 * inside lines.
 */
export function foreignBreakFilter(separator: LineSeparator): Extension {
  return EditorState.transactionFilter.of((transaction) => {
    if (!transaction.docChanged) return transaction;
    const fixes: { from: number; to: number; insert: string }[] = [];
    const document = transaction.newDoc;
    transaction.changes.iterChangedRanges((_fromA, _toA, fromB, toB) => {
      let position = fromB;
      for (;;) {
        const line = document.lineAt(position);
        const pattern = /\r\n|\r|\n/g;
        for (let match = pattern.exec(line.text); match !== null; match = pattern.exec(line.text)) {
          const from = line.from + match.index;
          const to = from + match[0].length;
          if (from < fromB || to > toB) continue;
          // A stray CR before a real break (CRLF into an LF note) or LF after
          // one (CRLF into a CR note) belongs to that break: remove it.
          const strayCr = separator === "\n" && match[0] === "\r" && to === line.to && line.number < document.lines;
          const strayLf = separator === "\r" && match[0] === "\n" && from === line.from && line.number > 1;
          fixes.push({ from, to, insert: strayCr || strayLf ? "" : separator });
        }
        if (line.to >= toB || line.number === document.lines) break;
        position = line.to + 1;
      }
    });
    if (fixes.length === 0) return transaction;
    const followUp: TransactionSpec = { changes: fixes, sequential: true };
    return [transaction, followUp];
  });
}

/** CodeMirror 6 used directly; the view lives exactly as long as one document key. */
export function MarkdownEditor({ documentKey, initialContent, separator, readOnly, label, onChange }: MarkdownEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const currentView = useRef<EditorView | null>(null);
  const configuration = useRef(new Compartment());
  const latest = useRef({ initialContent, separator, readOnly, label, onChange });
  useEffect(() => {
    latest.current = { initialContent, separator, readOnly, label, onChange };
  });

  useEffect(() => {
    const parent = host.current;
    if (parent === null) return;
    const options = latest.current;
    const extensions: Extension[] = [
      lineNumbers(),
      history(),
      drawSelection(),
      highlightActiveLine(),
      EditorView.lineWrapping,
      EditorView.darkTheme.of(false),
      markdown(),
      syntaxHighlighting(bookHighlightStyle, { fallback: true }),
      keymap.of([...defaultKeymap, ...historyKeymap]),
      configuration.current.of([
        EditorView.contentAttributes.of({ "aria-label": options.label }),
        EditorState.readOnly.of(options.readOnly), EditorView.editable.of(!options.readOnly),
      ]),
      EditorView.updateListener.of((update) => {
        if (update.docChanged) latest.current.onChange(update.state.sliceDoc());
      }),
    ];
    if (options.separator !== null) {
      extensions.push(EditorState.lineSeparator.of(options.separator), foreignBreakFilter(options.separator));
    }
    const view = new EditorView({
      parent,
      state: EditorState.create({ doc: options.initialContent, extensions }),
    });
    currentView.current = view;
    return () => { currentView.current = null; view.destroy(); };
  }, [documentKey]);

  useEffect(() => {
    currentView.current?.dispatch({ effects: configuration.current.reconfigure([
      EditorView.contentAttributes.of({ "aria-label": label }),
      EditorState.readOnly.of(readOnly), EditorView.editable.of(!readOnly),
    ]) });
  }, [label, readOnly]);

  return <div ref={host} className="page-editor h-full min-h-0" data-document-key={documentKey} />;
}
