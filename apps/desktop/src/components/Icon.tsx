import type { CSSProperties } from "react";

export type IconName = "ask" | "search" | "graph" | "note" | "folder" | "vault" | "refresh" | "save" | "sidebar" | "plus" | "quit"
  | "send" | "key" | "close" | "minimize" | "sparkle" | "pdf" | "code" | "text" | "globe";
const paths: Record<IconName, string> = {
  ask: "M4 5h16v11H9l-5 4V5ZM8 9h8M8 12h5",
  search: "M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0ZM15 15l6 6",
  graph: "M8 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM22 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM16 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM8 5l8 2M6 8l5 8M18 10l-4 6",
  note: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6ZM14 2v6h6M8 13h8M8 17h5",
  folder: "M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z",
  vault: "m12 3 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 16l9 5 9-5",
  refresh: "M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 2l1 4M18 18a8 8 0 0 1-13-2l-1-4",
  save: "M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h12l4 4v12a2 2 0 0 1-2 2ZM7 3v6h9V3M7 21v-8h10v8",
  sidebar: "M3 5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5ZM9 3v18",
  plus: "M12 5v14M5 12h14",
  quit: "M9 5H5v14h4M12 12h9M17 8l4 4-4 4",
  send: "M12 19V5M5 12l7-7 7 7",
  key: "M15 7a4 4 0 1 1-3.5 6L5 19.5V21H3v-3l6.5-6.5A4 4 0 0 1 15 7ZM16 9h.01",
  close: "M6 6l12 12M18 6 6 18",
  minimize: "M6 9l6 6 6-6",
  pdf: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6ZM14 2v6h6M8 13h2a1.5 1.5 0 0 1 0 3H8v-3ZM8 16v2M13 13v5M13 13h2.5M13 15.5h2",
  code: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6ZM14 2v6h6M10 13l-2 2 2 2M14 13l2 2-2 2",
  text: "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6ZM14 2v6h6M8 12h8M8 15h8M8 18h5",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3Z",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3ZM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16Z",
};

export function Icon({ name, size = 18, style }: { name: IconName; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}><path d={paths[name]} /></svg>;
}
