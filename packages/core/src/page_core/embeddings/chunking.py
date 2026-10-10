"""Split Markdown notes into chunks for embedding.

Each chunk is an exact substring of the note, located by the UTF-8 byte
interval [start_byte, end_byte) like ``page_core.domain.Chunk``. Chunks follow
Markdown structure: a heading starts a new chunk, blank lines separate blocks,
and fenced code blocks are never split at blank lines. Blocks are packed into
chunks of at most ``max_chars`` characters; a longer block is split at line
boundaries, and a longer line at whitespace.
"""

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

DEFAULT_MAX_CHARS = 1200

_HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t#]*$")
# CommonMark fences: a backtick opener's info string may not contain backticks.
_FENCE_OPEN = re.compile(r"^ {0,3}(?:(`{3,})[^`]*|(~{3,}).*)$")


@dataclass(frozen=True, slots=True)
class TextChunk:
    ordinal: int
    text: str
    start_byte: int
    end_byte: int
    heading: str | None


@dataclass(slots=True)
class _Block:
    start: int
    end: int
    heading: str | None
    starts_section: bool


def chunk_markdown(content: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[TextChunk]:
    """Return the chunks of ``content`` in document order."""
    if not isinstance(content, str):
        raise TypeError(f"content must be str, got {type(content).__name__}")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError(f"max_chars must be a positive int, got {max_chars!r}")

    spans: list[tuple[int, int, str | None]] = []
    current: tuple[int, int, str | None] | None = None
    for block in _blocks(content):
        if block.end - block.start > max_chars:
            if current:
                spans.append(current)
                current = None
            spans.extend(
                (start, end, block.heading)
                for start, end in _split_long(content, block.start, block.end, max_chars)
            )
            continue
        if current and (block.starts_section or block.end - current[0] > max_chars):
            spans.append(current)
            current = None
        if current:
            current = (current[0], block.end, current[2])
        else:
            current = (block.start, block.end, block.heading)
    if current:
        spans.append(current)

    chunks: list[TextChunk] = []
    char_cursor = 0
    byte_cursor = 0
    for start, end, heading in spans:
        while start < end and content[start].isspace():
            start += 1
        while end > start and content[end - 1].isspace():
            end -= 1
        if start == end:
            continue
        # Spans are in document order, so byte offsets can be computed incrementally.
        start_byte = byte_cursor + len(content[char_cursor:start].encode("utf-8"))
        text = content[start:end]
        end_byte = start_byte + len(text.encode("utf-8"))
        char_cursor, byte_cursor = end, end_byte
        chunks.append(TextChunk(len(chunks), text, start_byte, end_byte, heading))
    return chunks


def embedding_text(path: PurePosixPath, chunk: TextChunk) -> str:
    """The text embedded for a chunk: note title and section heading, then the chunk.

    The title and heading give short chunks the context a reader would have.
    The stored excerpt is always the raw chunk text.
    """
    parts = [path.stem]
    if chunk.heading and not _HEADING.match(chunk.text.split("\n", 1)[0]):
        parts.append(chunk.heading)
    parts.append(chunk.text)
    return "\n\n".join(parts)


def _lines(content: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    position = 0
    for line in content.splitlines(keepends=True):
        lines.append((position, line))
        position += len(line)
    return lines


def _front_matter_end(lines: list[tuple[int, str]]) -> int:
    """Index of the first line after a leading YAML front matter block, else 0."""
    if not lines or lines[0][1].rstrip("\r\n") != "---":
        return 0
    for index in range(1, len(lines)):
        if lines[index][1].rstrip("\r\n") in {"---", "..."}:
            return index + 1
    return 0


def _blocks(content: str) -> list[_Block]:
    lines = _lines(content)
    blocks: list[_Block] = []
    heading: str | None = None
    block: _Block | None = None
    fence: re.Pattern[str] | None = None
    for position, line in lines[_front_matter_end(lines):]:
        end = position + len(line)
        bare = line.rstrip("\r\n")
        if fence is not None:
            assert block is not None
            block.end = end
            if fence.match(bare):
                fence = None
            continue
        heading_match = _HEADING.match(bare)
        if heading_match:
            if block:
                blocks.append(block)
            heading = heading_match.group(1).strip()
            block = _Block(position, end, heading, starts_section=True)
            continue
        if not bare.strip():
            if block:
                blocks.append(block)
                block = None
            continue
        fence_match = _FENCE_OPEN.match(bare)
        if fence_match:
            fence = _closing_fence(fence_match.group(1) or fence_match.group(2))
        if block:
            block.end = end
        else:
            block = _Block(position, end, heading, starts_section=False)
    if block:
        blocks.append(block)
    return blocks


def _closing_fence(opener: str) -> re.Pattern[str]:
    """Match a line that closes a fence opened by ``opener``.

    The closer uses the same character, is at least as long as the opener,
    and has nothing but whitespace after it.
    """
    return re.compile(rf"^ {{0,3}}{re.escape(opener[0])}{{{len(opener)},}}[ \t]*$")


def _split_long(content: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split [start, end) into pieces of at most ``max_chars`` characters."""
    pieces: list[tuple[int, int]] = []
    piece_start = start
    while end - piece_start > max_chars:
        limit = piece_start + max_chars
        cut = content.rfind("\n", piece_start, limit)
        if cut <= piece_start:
            cut = max(
                content.rfind(" ", piece_start, limit),
                content.rfind("\t", piece_start, limit),
            )
        cut = cut + 1 if cut > piece_start else limit
        pieces.append((piece_start, cut))
        piece_start = cut
    if piece_start < end:
        pieces.append((piece_start, end))
    return pieces
