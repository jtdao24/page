"""Pure wiki-link parsing and deterministic graphs built from canonical notes.

No I/O or generated identities: nodes keep the UUIDs supplied by persistence.
Graphs are derived snapshots; moving a file does not rewrite its source links.
"""

import re
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from page_core.domain import Link, Note, validate_note_path


@dataclass(frozen=True, slots=True)
class WikiReference:
    target_reference: str
    alias: str | None
    line: int

    def __post_init__(self) -> None:
        if not isinstance(self.target_reference, str) or (self.alias is not None and not isinstance(self.alias, str)):
            raise TypeError("reference and alias must be strings")
        if type(self.line) is not int:
            raise TypeError("line must be int")
        if not self.target_reference.strip() or self.line < 1:
            raise ValueError("reference must be nonblank and line must be positive")


@dataclass(frozen=True, slots=True)
class GraphNode:
    id: UUID
    relative_path: PurePosixPath

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise TypeError("id must be UUID")
        validate_note_path(self.relative_path)


@dataclass(frozen=True, slots=True)
class GraphLink:
    link: Link
    alias: str | None
    line: int
    unresolved_reason: Literal["missing", "ambiguous", "invalid"] | None

    def __post_init__(self) -> None:
        if not isinstance(self.link, Link):
            raise TypeError("link must be Link")
        WikiReference(self.link.target_reference, self.alias, self.line)
        if self.unresolved_reason is not None and not isinstance(self.unresolved_reason, str):
            raise TypeError("unresolved_reason must be str or None")
        if self.link.target_note_id is None:
            if self.unresolved_reason not in {"missing", "ambiguous", "invalid"}:
                raise ValueError("unresolved links must have a known reason")
        elif self.unresolved_reason is not None:
            raise ValueError("resolved links cannot have an unresolved reason")


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    vault_id: UUID
    nodes: tuple[GraphNode, ...]
    links: tuple[GraphLink, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.vault_id, UUID) or not isinstance(self.nodes, tuple) or not isinstance(self.links, tuple):
            raise TypeError("graph requires UUID and immutable tuples")
        if any(not isinstance(node, GraphNode) for node in self.nodes) or any(not isinstance(edge, GraphLink) for edge in self.links):
            raise TypeError("graph requires GraphNode and GraphLink values")
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes) or len({node.relative_path for node in self.nodes}) != len(self.nodes):
            raise ValueError("node identities and paths must be unique")
        if any(edge.link.source_note_id not in ids or
               (edge.link.target_note_id is not None and edge.link.target_note_id not in ids) for edge in self.links):
            raise ValueError("link endpoints must belong to the graph")

    def backlinks(self, note_id: UUID) -> tuple[GraphLink, ...]:
        if not isinstance(note_id, UUID):
            raise TypeError("note_id must be UUID")
        return tuple(edge for edge in self.links if edge.link.target_note_id == note_id)


def _escaped(text: str, position: int) -> bool:
    count = 0
    while position > 0 and text[position - 1] == "\\":
        count += 1
        position -= 1
    return count % 2 == 1


def _mask(content: str) -> str:
    chars = list(content)

    def hide(start: int, end: int) -> None:
        for index in range(start, end):
            if chars[index] not in "\r\n":
                chars[index] = " "

    position = 0
    fence: tuple[str, int] | None = None
    frontmatter = content.lstrip("\ufeff").startswith(("---\n", "---\r"))
    first_line = True
    newline = re.compile(r"\r\n|\r|\n")
    ticks = re.compile(r"`+")
    while position < len(content):
        if position == 0 or content[position - 1] in "\r\n":
            end_match = newline.search(content, position)
            end = len(content) if end_match is None else end_match.end()
            line = content[position:end]
            marker = re.match(r"^ {0,3}(?:> ?)*(`{3,}|~{3,})(.*)", line.rstrip("\r\n"))
            if frontmatter:
                hide(position, end)
                if not first_line and line.strip() in {"---", "..."}:
                    frontmatter = False
                first_line = False
                position = end
                continue
            if fence:
                hide(position, end)
                if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                    fence = None
                position = end
                continue
            if marker and (marker[1][0] != "`" or "`" not in marker[2]):
                fence = marker[1][0], len(marker[1])
                hide(position, end)
                position = end
                continue
            if line.startswith(("    ", "\t")):
                hide(position, end)
                position = end
                continue
        if content.startswith("<!--", position) and not _escaped(content, position):
            close = content.find("-->", position + 4)
            end = len(content) if close < 0 else close + 3
            hide(position, end)
            position = end
            continue
        if content[position] == "`" and not _escaped(content, position):
            run = ticks.match(content, position)
            assert run is not None
            after = run.end()
            close = re.compile(r"(?<!`)" + re.escape(run[0]) + r"(?!`)").search(content, after)
            if close:
                end = close.end()
                hide(position, end)
                position = end
                continue
            position = after
            continue
        position += 1
    return "".join(chars)


def parse_wiki_links(content: str) -> tuple[WikiReference, ...]:
    """Parse [[target#fragment|alias]] and ![[embeds]], excluding code/comments.

    References keep their fragment spelling; resolution targets the note only.
    Empty references and malformed/nested/multiline brackets are ignored.
    """
    if not isinstance(content, str):
        raise TypeError("content must be str")
    visible = _mask(content)
    result: list[WikiReference] = []
    # splitlines recognizes Unicode separators too; source line numbers here
    # deliberately follow Markdown's CR, LF and CRLF line endings only.
    starts = [0] + [match.end() for match in re.finditer(r"\r\n|\r|\n", content)]
    depth = 0
    opening = 0
    nested = False
    for token in re.finditer(r"\[\[|\]\]|\r\n|\r|\n", visible):
        if token[0] in {"\r", "\n", "\r\n"}:
            depth = 0
            continue
        if _escaped(visible, token.start()):
            continue
        if token[0] == "[[":
            if depth == 0:
                opening = token.end()
                nested = False
            else:
                nested = True
            depth += 1
        elif depth:
            depth -= 1
            if depth or nested:
                continue
            body = visible[opening:token.start()]
            if "[" in body or "]" in body:
                continue
            target, separator, alias = body.partition("|")
            target = target.strip()
            if target:
                result.append(WikiReference(target, alias.strip() if separator else None,
                                            bisect_right(starts, opening - 2)))
    return tuple(result)


def _resolve(source: Note, reference: str, by_path: dict[str, Note],
             by_stem: dict[str, list[Note]]) -> tuple[UUID | None, Literal["missing", "ambiguous", "invalid"] | None]:
    target = reference.split("#", 1)[0].strip()
    if not target:
        return source.id, None
    if "\\" in target or "\x00" in target or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None, "invalid"
    # Absolute slash denotes the vault root, never the host filesystem.
    root_relative = target.startswith("/")
    target = target.lstrip("/") if root_relative else target
    if target.endswith(".md"):
        target = target[:-3]
    parts = target.split("/")
    if not target or any(part in {"", ".."} for part in parts):
        return None, "invalid"
    if parts[0] == ".":
        path = str(source.relative_path.parent / ("/".join(parts[1:]) + ".md"))
        note = by_path.get(path)
        return (note.id, None) if note else (None, "missing")
    if any(part == "." for part in parts):
        return None, "invalid"
    if "/" in target or root_relative:
        note = by_path.get(target + ".md")
        return (note.id, None) if note else (None, "missing")
    local = by_path.get(str(source.relative_path.parent / (target + ".md")))
    if local:
        return local.id, None
    matches = by_stem.get(target, [])
    if len(matches) == 1:
        return matches[0].id, None
    return None, "ambiguous" if matches else "missing"


def build_graph(vault_id: UUID, notes: tuple[Note, ...]) -> GraphSnapshot:
    """Build a stable directed snapshot; repeated links retain source locations."""
    if not isinstance(vault_id, UUID) or not isinstance(notes, tuple):
        raise TypeError("vault_id must be UUID and notes must be tuple")
    if any(not isinstance(note, Note) for note in notes):
        raise TypeError("notes must contain Note values")
    if any(note.vault_id != vault_id for note in notes):
        raise ValueError("all notes must belong to the graph vault")
    if len({note.id for note in notes}) != len(notes) or len({note.relative_path for note in notes}) != len(notes):
        raise ValueError("note identities and paths must be unique")
    ordered = sorted(notes, key=lambda note: (str(note.relative_path), str(note.id)))
    by_path = {str(note.relative_path): note for note in ordered}
    by_stem: dict[str, list[Note]] = {}
    for note in ordered:
        by_stem.setdefault(note.relative_path.stem, []).append(note)
    links: list[GraphLink] = []
    for note in ordered:
        for reference in parse_wiki_links(note.content):
            target, reason = _resolve(note, reference.target_reference, by_path, by_stem)
            links.append(GraphLink(Link(note.id, reference.target_reference, target),
                                   reference.alias, reference.line, reason))
    return GraphSnapshot(vault_id, tuple(GraphNode(note.id, note.relative_path) for note in ordered), tuple(links))
