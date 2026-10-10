"""Heading-aware source spans constrained by the embedding tokenizer."""

import re
from dataclasses import dataclass
from uuid import UUID, uuid5

from page_core.domain import Chunk

CHUNK_VERSION = "markdown-v1"


@dataclass(frozen=True)
class MarkdownChunk:
    chunk: Chunk
    headings: tuple[str, ...]
    start_line: int
    end_line: int


def chunk_markdown(note_id: UUID, text: str, tokenizer, *, budget: int = 254) -> list[MarkdownChunk]:
    """Keep exact UTF-8 source spans; reserve two MiniLM special tokens.

    Sections never cross headings. Prefer paragraph/line breaks, splitting long
    paragraphs by characters with exact tokenizer checks. Fences mask headings.
    Heading ancestry is metadata, never silently added outside the token budget.
    """
    if not 1 <= budget <= 254:
        raise ValueError("token budget must be between 1 and 254")
    sections = []
    ancestry: list[tuple[int, str]] = []
    start = offset = 0
    headings: tuple[str, ...] = ()
    fence: str | None = None
    fence_length = 0
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence, fence_length = run[0], len(run)
            elif run[0] == fence and len(run) >= fence_length and not line[marker.end():].strip():
                fence = None
        heading = None if fence else re.match(r"^ {0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        setext = (fence is None and index + 1 < len(lines)
                  and line.strip() and re.match(r"^ {0,3}(=+|-+)\s*$", lines[index + 1]))
        if heading or setext:
            if offset > start:
                sections.append((start, offset, headings))
            level = len(heading.group(1)) if heading else (1 if lines[index + 1].lstrip().startswith("=") else 2)
            title = heading.group(2) if heading else line.strip()
            ancestry = [(n, h) for n, h in ancestry if n < level]
            ancestry.append((level, title))
            headings = tuple(h for _, h in ancestry)
            start = offset
        offset += len(line)
    if offset > start:
        sections.append((start, offset, headings))

    byte_offsets = [0]
    for char in text:
        byte_offsets.append(byte_offsets[-1] + len(char.encode("utf-8")))

    def count(value: str) -> int:
        return len(tokenizer.encode(value, add_special_tokens=False, verbose=False))

    result = []
    for begin, end, headings in sections:
        while begin < end:
            if count(text[begin:end]) <= budget:
                stop = end
            else:
                # Grow a valid prefix; verify the final slice independently.
                low, high = begin + 1, end
                stop = begin
                while low <= high:
                    middle = (low + high) // 2
                    if count(text[begin:middle]) <= budget:
                        stop, low = middle, middle + 1
                    else:
                        high = middle - 1
                if stop == begin:
                    raise ValueError("a source character exceeds the token budget")
                prefix = text[begin:stop]
                boundary = prefix.rfind("\n\n")
                if boundary < len(prefix) // 2:
                    boundary = prefix.rfind("\n")
                if boundary < len(prefix) // 2:
                    boundary = prefix.rfind(" ")
                if boundary >= len(prefix) // 2:
                    stop = begin + boundary + 1
            value = text[begin:stop]
            tokens = count(value)
            if tokens > budget:
                raise ValueError("chunk exceeds token budget")
            if value.strip():
                ordinal = len(result)
                chunk = Chunk(uuid5(note_id, f"{CHUNK_VERSION}:{ordinal}:{value}"), note_id,
                              ordinal, value, byte_offsets[begin], byte_offsets[stop], tokens)
                result.append(MarkdownChunk(chunk, headings,
                    text.count("\n", 0, begin) + 1,
                    text.count("\n", 0, stop - 1) + 1))
            begin = stop
    return result
