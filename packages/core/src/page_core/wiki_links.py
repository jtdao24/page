"""Parse and resolve Obsidian-style wiki links in Markdown notes."""

from __future__ import annotations

import re
from dataclasses import dataclass

WIKI_LINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")


@dataclass(frozen=True)
class ExtractedLink:
    title: str
    display_text: str | None
    raw: str
    start: int
    end: int


@dataclass(frozen=True)
class NoteRef:
    id: str
    title: str
    path: str


@dataclass(frozen=True)
class ResolvedLink:
    title: str
    display_text: str | None
    raw: str
    start: int
    end: int
    target_id: str | None
    excerpt: str

    @property
    def resolved(self) -> bool:
        return self.target_id is not None


def _is_line_start(text: str, index: int) -> bool:
    return index == 0 or text[index - 1] == "\n"


def code_spans(text: str) -> list[tuple[int, int]]:
    """Return [start, end) ranges for fenced and inline code."""
    spans: list[tuple[int, int]] = []
    length = len(text)
    index = 0
    while index < length:
        if _is_line_start(text, index) and text.startswith("```", index):
            line_end = text.find("\n", index)
            search_from = length if line_end == -1 else line_end + 1
            close = search_from
            found = False
            while close < length:
                if _is_line_start(text, close) and text.startswith("```", close):
                    close_line = text.find("\n", close)
                    end = length if close_line == -1 else close_line + 1
                    spans.append((index, end))
                    index = end
                    found = True
                    break
                next_line = text.find("\n", close)
                close = length if next_line == -1 else next_line + 1
            if not found:
                spans.append((index, length))
                break
            continue
        if text[index] == "`":
            end = index + 1
            while end < length and text[end] not in ("`", "\n"):
                end += 1
            if end < length and text[end] == "`":
                spans.append((index, end + 1))
                index = end + 1
                continue
        index += 1
    return spans


def _in_span(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def parse_wiki_target(inner: str) -> tuple[str, str | None]:
    title, separator, alias = inner.partition("|")
    cleaned_title = title.strip()
    if not separator:
        return cleaned_title, None
    display = alias.strip()
    return cleaned_title, display or None


def extract_wiki_links(text: str) -> list[ExtractedLink]:
    masked = code_spans(text)
    links: list[ExtractedLink] = []
    for match in WIKI_LINK_RE.finditer(text):
        if _in_span(match.start(), masked):
            continue
        title, display_text = parse_wiki_target(match.group(1))
        if not title:
            continue
        links.append(
            ExtractedLink(
                title=title,
                display_text=display_text,
                raw=match.group(0),
                start=match.start(),
                end=match.end(),
            )
        )
    return links


def excerpt_for(text: str, position: int) -> str:
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end].strip()


def _normalize_key(value: str) -> str:
    key = value.strip().replace("\\", "/")
    if key.lower().endswith(".md"):
        key = key[: -len(".md")]
    return key.casefold()


def resolve_title(title: str, notes: list[NoteRef]) -> str | None:
    """Resolve a wiki-link title to a note id.

    Matching order:
    1. Unique case-insensitive match on relative path (with or without ``.md``).
    2. Unique case-insensitive match on filename stem (the note title).
    3. If several notes share the title, pick the shortest relative path, then
       lexicographic order. Duplicate titles therefore resolve predictably
       instead of remaining unresolved.
    """
    wanted = _normalize_key(title)
    if not wanted:
        return None

    path_matches = [
        note
        for note in notes
        if _normalize_key(note.path) == wanted or _normalize_key(note.id) == wanted
    ]
    if len(path_matches) == 1:
        return path_matches[0].id
    if len(path_matches) > 1:
        chosen = sorted(path_matches, key=lambda note: (len(note.path), note.path.casefold()))[0]
        return chosen.id

    title_matches = [note for note in notes if note.title.casefold() == wanted]
    if not title_matches:
        return None
    chosen = sorted(title_matches, key=lambda note: (len(note.path), note.path.casefold()))[0]
    return chosen.id


def resolve_links(text: str, notes: list[NoteRef]) -> list[ResolvedLink]:
    resolved: list[ResolvedLink] = []
    for link in extract_wiki_links(text):
        resolved.append(
            ResolvedLink(
                title=link.title,
                display_text=link.display_text,
                raw=link.raw,
                start=link.start,
                end=link.end,
                target_id=resolve_title(link.title, notes),
                excerpt=excerpt_for(text, link.start),
            )
        )
    return resolved
