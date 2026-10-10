import { collectionOf } from "./library";
import type { ContextNote } from "./library";

const COLORS = ["#365f88", "#567ca2", "#7293b1", "#426c85", "#6a819a", "#4d6587"];
export function collectionColor(name: string) {
  const hash = Array.from(name).reduce((value, character) => (value * 31 + character.charCodeAt(0)) >>> 0, 0);
  return COLORS[hash % COLORS.length];
}

export function entryGraph(notes: ContextNote[]) {
  const ordered = [...notes].sort((a, b) => a.id.localeCompare(b.id));
  const radius = 70 + Math.sqrt(Math.max(0, ordered.length - 1)) * 66;
  const width = Math.max(960, radius * 2 + 240);
  const height = Math.max(620, radius * 2 + 140);
  const nodes = ordered.map((note, index) => {
    const angle = index * Math.PI * (3 - Math.sqrt(5));
    const distance = index === 0 ? 30 : 70 + Math.sqrt(index) * 66;
    return { note, x: width / 2 + Math.cos(angle) * distance,
      y: height / 2 + Math.sin(angle) * distance, color: collectionColor(collectionOf(note)) };
  });
  const groups = new Map<string, typeof nodes>();
  for (const node of nodes) {
    const name = collectionOf(node.note);
    const group = groups.get(name) ?? [];
    group.push(node); groups.set(name, group);
  }
  const edges: { key: string; from: typeof nodes[number]; to: typeof nodes[number] }[] = [];
  const seen = new Set<string>();
  const connect = (from: typeof nodes[number], to: typeof nodes[number]) => {
    if (from === to) return;
    const key = [from.note.id, to.note.id].sort().join(":");
    if (!seen.has(key)) { seen.add(key); edges.push({ key, from, to }); }
  };
  // Linear-size visual connections for shared folders; these are not learned
  // semantic relationships or knowledge-graph edges from Page Core.
  for (const group of groups.values()) {
    for (let i = 1; i < group.length; i++) {
      connect(group[0], group[i]); connect(group[i - 1], group[i]);
    }
    if (group.length > 2) connect(group[group.length - 1], group[0]);
  }
  return { width, height, nodes, edges };
}
