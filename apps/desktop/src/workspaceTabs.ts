import type { ContextNote } from "./library";

export type PaneSide = "left" | "right";
export type WorkspaceTabs = {
  entries: ContextNote[];
  panes: Record<PaneSide, string[]>;
  selected: Record<PaneSide, string>;
  focused: PaneSide;
};

export function initialTabs(): WorkspaceTabs {
  return { entries: [], panes: { left: ["graph"], right: [] }, selected: { left: "graph", right: "" }, focused: "left" };
}

export function paneOf(state: WorkspaceTabs, id: string): PaneSide {
  return state.panes.right.includes(id) ? "right" : "left";
}

export function selectTab(state: WorkspaceTabs, id: string): WorkspaceTabs {
  const side = paneOf(state, id);
  if (!state.panes[side].includes(id)) return state;
  return { ...state, selected: { ...state.selected, [side]: id }, focused: side };
}

export function openTab(state: WorkspaceTabs, note: ContextNote): WorkspaceTabs {
  if (state.entries.some((entry) => entry.id === note.id)) return selectTab(state, note.id);
  const side = state.focused;
  return { ...state, entries: [...state.entries, note], panes: { ...state.panes, [side]: [...state.panes[side], note.id] },
    selected: { ...state.selected, [side]: note.id } };
}

function removeFromPane(state: WorkspaceTabs, id: string): WorkspaceTabs {
  const side = paneOf(state, id);
  const ids = state.panes[side];
  const remaining = ids.filter((item) => item !== id);
  const fallback = remaining[Math.max(0, ids.indexOf(id) - 1)] ?? "";
  return { ...state, panes: { ...state.panes, [side]: remaining },
    selected: { ...state.selected, [side]: state.selected[side] === id ? fallback : state.selected[side] } };
}

// Keep one primary pane when moving/closing the last tab in either pane.
function collapseEmptyPane(state: WorkspaceTabs): WorkspaceTabs {
  if (!state.panes.left.length) return { ...state, panes: { left: state.panes.right, right: [] },
    selected: { left: state.selected.right, right: "" }, focused: "left" };
  if (!state.panes.right.length && state.focused === "right") return { ...state, focused: "left" };
  return state;
}

export function closeTab(state: WorkspaceTabs, id: string): WorkspaceTabs {
  if (id === "graph" || !state.entries.some((note) => note.id === id)) return state;
  return collapseEmptyPane({ ...removeFromPane(state, id), entries: state.entries.filter((note) => note.id !== id) });
}

export function moveTab(state: WorkspaceTabs, id: string, destination: PaneSide, split = false): WorkspaceTabs {
  const source = paneOf(state, id);
  if (!state.panes[source].includes(id)) return state;
  if (split && destination === "left" && !state.panes.right.length && state.panes.left.length > 1) {
    const remaining = state.panes.left.filter((item) => item !== id);
    return { ...state, panes: { left: [id], right: remaining }, selected: { left: id,
      right: state.selected.left !== id ? state.selected.left : remaining[0] }, focused: "left" };
  }
  if (source === destination) return selectTab(state, id);
  const removed = removeFromPane(state, id);
  return collapseEmptyPane({ ...removed, panes: { ...removed.panes, [destination]: [...removed.panes[destination], id] },
    selected: { ...removed.selected, [destination]: id }, focused: destination });
}
