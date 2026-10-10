import { RangeSetBuilder } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import type { NoteSummary } from "./types";
import { extractWikiLinks } from "./wikiLinks";

const resolvedMark = Decoration.mark({ class: "wiki-link-resolved", attributes: { "data-wiki-link": "resolved" } });
const unresolvedMark = Decoration.mark({
  class: "wiki-link-unresolved",
  attributes: { "data-wiki-link": "unresolved" },
});

export function wikiLinkExtension(notes: NoteSummary[], onOpen: (noteId: string) => void) {
  const plugin = ViewPlugin.fromClass(
    class {
      decorations: DecorationSet;

      constructor(view: EditorView) {
        this.decorations = this.build(view);
      }

      update(update: ViewUpdate): void {
        if (update.docChanged || update.viewportChanged) {
          this.decorations = this.build(update.view);
        }
      }

      build(view: EditorView): DecorationSet {
        const builder = new RangeSetBuilder<Decoration>();
        const text = view.state.doc.toString();
        for (const link of extractWikiLinks(text, notes)) {
          builder.add(link.start, link.end, link.targetId ? resolvedMark : unresolvedMark);
        }
        return builder.finish();
      }
    },
    {
      decorations: (value) => value.decorations,
      eventHandlers: {
        click: (event, view) => {
          const target = event.target;
          if (!(target instanceof HTMLElement) || !target.closest(".wiki-link-resolved")) {
            return false;
          }
          const position = view.posAtCoords({ x: event.clientX, y: event.clientY });
          if (position === null) {
            return false;
          }
          const link = extractWikiLinks(view.state.doc.toString(), notes).find(
            (item) => position >= item.start && position <= item.end && item.targetId,
          );
          if (!link?.targetId) {
            return false;
          }
          event.preventDefault();
          onOpen(link.targetId);
          return true;
        },
      },
    },
  );

  return [
    plugin,
    EditorView.theme({
      ".wiki-link-resolved": {
        color: "#1d4ed8",
        textDecoration: "underline",
        cursor: "pointer",
      },
      ".wiki-link-unresolved": {
        color: "#be123c",
        textDecoration: "underline dashed",
      },
    }),
  ];
}
