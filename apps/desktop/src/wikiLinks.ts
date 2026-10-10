import type { ExtractedWikiLink, NoteSummary } from "./types";

const WIKI_LINK_RE = /\[\[([^[\]]+?)\]\]/g;

function isLineStart(text: string, index: number): boolean {
  return index === 0 || text[index - 1] === "\n";
}

export function codeSpans(text: string): Array<[number, number]> {
  const spans: Array<[number, number]> = [];
  const length = text.length;
  let index = 0;
  while (index < length) {
    if (isLineStart(text, index) && text.startsWith("```", index)) {
      const lineEnd = text.indexOf("\n", index);
      let close = lineEnd === -1 ? length : lineEnd + 1;
      let found = false;
      while (close < length) {
        if (isLineStart(text, close) && text.startsWith("```", close)) {
          const closeLine = text.indexOf("\n", close);
          const end = closeLine === -1 ? length : closeLine + 1;
          spans.push([index, end]);
          index = end;
          found = true;
          break;
        }
        const nextLine = text.indexOf("\n", close);
        close = nextLine === -1 ? length : nextLine + 1;
      }
      if (!found) {
        spans.push([index, length]);
        break;
      }
      continue;
    }
    if (text[index] === "`") {
      let end = index + 1;
      while (end < length && text[end] !== "`" && text[end] !== "\n") {
        end += 1;
      }
      if (end < length && text[end] === "`") {
        spans.push([index, end + 1]);
        index = end + 1;
        continue;
      }
    }
    index += 1;
  }
  return spans;
}

function inSpan(position: number, spans: Array<[number, number]>): boolean {
  return spans.some(([start, end]) => position >= start && position < end);
}

export function parseWikiTarget(inner: string): { title: string; displayText: string | null } {
  const separator = inner.indexOf("|");
  if (separator === -1) {
    return { title: inner.trim(), displayText: null };
  }
  const title = inner.slice(0, separator).trim();
  const displayText = inner.slice(separator + 1).trim();
  return { title, displayText: displayText || null };
}

function normalizeKey(value: string): string {
  let key = value.trim().replaceAll("\\", "/");
  if (key.toLowerCase().endsWith(".md")) {
    key = key.slice(0, -3);
  }
  return key.toLowerCase();
}

export function resolveTitle(title: string, notes: NoteSummary[]): string | null {
  const wanted = normalizeKey(title);
  if (!wanted) {
    return null;
  }
  const pathMatches = notes.filter(
    (note) => normalizeKey(note.path) === wanted || normalizeKey(note.id) === wanted,
  );
  if (pathMatches.length === 1) {
    return pathMatches[0].id;
  }
  if (pathMatches.length > 1) {
    return [...pathMatches].sort((a, b) => a.path.length - b.path.length || a.path.localeCompare(b.path))[0]
      .id;
  }
  const titleMatches = notes.filter((note) => note.title.toLowerCase() === wanted);
  if (titleMatches.length === 0) {
    return null;
  }
  return [...titleMatches].sort((a, b) => a.path.length - b.path.length || a.path.localeCompare(b.path))[0]
    .id;
}

export function extractWikiLinks(text: string, notes: NoteSummary[]): ExtractedWikiLink[] {
  const masked = codeSpans(text);
  const links: ExtractedWikiLink[] = [];
  for (const match of text.matchAll(WIKI_LINK_RE)) {
    const start = match.index ?? 0;
    if (inSpan(start, masked)) {
      continue;
    }
    const { title, displayText } = parseWikiTarget(match[1]);
    if (!title) {
      continue;
    }
    links.push({
      title,
      displayText,
      raw: match[0],
      start,
      end: start + match[0].length,
      targetId: resolveTitle(title, notes),
    });
  }
  return links;
}
