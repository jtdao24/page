from pathlib import PurePosixPath

import pytest

from page_core.embeddings.chunking import TextChunk, chunk_markdown, embedding_text, heading_text


def _bytes(content: str, chunk: TextChunk) -> str:
    return content.encode("utf-8")[chunk.start_byte : chunk.end_byte].decode("utf-8")


def test_chunks_are_exact_byte_ranges_of_unicode_content() -> None:
    content = "# Café ☕\n\nNaïve résumé 日本語.\n\n## Next\n\nEmoji 🎉 here.\n"

    chunks = chunk_markdown(content)

    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert _bytes(content, chunk) == chunk.text


def test_headings_start_new_chunks_and_label_them() -> None:
    content = "Intro line.\n\n# Logic\n\nGates.\n\nMore gates.\n\n## Maps\n\nKarnaugh.\n"

    chunks = chunk_markdown(content)

    assert [chunk.text for chunk in chunks] == [
        "Intro line.",
        "# Logic\n\nGates.\n\nMore gates.",
        "## Maps\n\nKarnaugh.",
    ]
    assert [chunk.heading for chunk in chunks] == [None, "Logic", "Maps"]


def test_fenced_code_is_not_split_at_blank_lines() -> None:
    content = "Text.\n\n```python\ndef a():\n\n    return 1\n```\n\nAfter.\n"

    chunks = chunk_markdown(content, max_chars=1000)

    assert len(chunks) == 1
    assert "def a():\n\n    return 1" in chunks[0].text


def test_heading_inside_fence_is_not_a_heading() -> None:
    content = "# Real\n\n```\n# not a heading\n```\n"

    chunks = chunk_markdown(content)

    assert [chunk.heading for chunk in chunks] == ["Real"]


def test_long_blocks_are_split_within_the_limit() -> None:
    content = " ".join(f"word{i}" for i in range(400)) + "\n"

    chunks = chunk_markdown(content, max_chars=100)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 100 for chunk in chunks)
    assert " ".join(chunk.text for chunk in chunks) == content.strip()
    for chunk in chunks:
        assert _bytes(content, chunk) == chunk.text


def test_small_blocks_are_packed_together() -> None:
    content = "One.\n\nTwo.\n\nThree.\n"

    assert [chunk.text for chunk in chunk_markdown(content)] == ["One.\n\nTwo.\n\nThree."]
    assert len(chunk_markdown(content, max_chars=8)) == 3


def test_front_matter_is_skipped() -> None:
    content = "---\ntags: [a]\n---\nBody text.\n"

    assert [chunk.text for chunk in chunk_markdown(content)] == ["Body text."]


@pytest.mark.parametrize("content", ["", "\n\n", "   \n\t\n"])
def test_blank_notes_have_no_chunks(content: str) -> None:
    assert chunk_markdown(content) == []


def test_crlf_line_endings_keep_exact_offsets() -> None:
    content = "# Title\r\n\r\nLine one.\r\n\r\n# Second\r\n\r\nLine two.\r\n"

    chunks = chunk_markdown(content)

    assert len(chunks) == 2
    for chunk in chunks:
        assert _bytes(content, chunk) == chunk.text


def test_invalid_arguments_are_rejected() -> None:
    with pytest.raises(TypeError):
        chunk_markdown(b"bytes")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        chunk_markdown("text", max_chars=0)


def test_embedding_text_adds_title_and_missing_heading() -> None:
    path = PurePosixPath("notes/Digital Logic.md")
    with_heading = TextChunk(0, "## Maps\n\nKarnaugh.", 0, 10, "Maps")
    continued = TextChunk(1, "More about maps.", 20, 36, "Maps")

    assert embedding_text(path, with_heading) == "Digital Logic\n\n## Maps\n\nKarnaugh."
    assert embedding_text(path, continued) == "Digital Logic\n\nMaps\n\nMore about maps."


def test_longer_fence_is_not_closed_by_a_shorter_one() -> None:
    content = "````md\n```\n\n# Not a heading\n\n```\n````\n\n# Real\n\nAfter.\n"

    chunks = chunk_markdown(content)

    assert [chunk.heading for chunk in chunks] == [None, "Real"]
    assert chunks[0].text == content.split("\n\n# Real")[0]


def test_fence_line_with_trailing_text_does_not_close() -> None:
    content = "```\ncode\n```text\n\n# Still code\n```\n\n# Real\n"

    chunks = chunk_markdown(content)

    assert [chunk.heading for chunk in chunks] == [None, "Real"]
    assert "# Still code" in chunks[0].text


def test_fence_closes_only_with_the_same_character() -> None:
    content = "~~~\n```\n\n# Still code\n~~~~\n\n# Real\n"

    chunks = chunk_markdown(content)

    assert [chunk.heading for chunk in chunks] == [None, "Real"]


def test_longer_closing_fence_with_trailing_spaces_closes() -> None:
    content = "```\ncode\n`````  \n\n# Real\n"

    assert [chunk.heading for chunk in chunk_markdown(content)] == [None, "Real"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("# C#", "C#"),
        ("# value###", "value###"),
        ("# value ###", "value"),
        ("## value ##   ", "value"),
        ("# a # b", "a # b"),
        ("# foo#bar ##", "foo#bar"),
        ("## ###", ""),
        ("#", ""),
        ("   ### indented", "indented"),
        ("#5 bolts", None),
        ("####### seven", None),
        ("    # code block", None),
    ],
)
def test_heading_text_follows_commonmark(line: str, expected: str | None) -> None:
    assert heading_text(line) == expected


def test_heading_with_trailing_hash_keeps_its_label() -> None:
    content = "# C#\n\nGenerics.\n\n# value###\n\nText.\n\n# value ###\n\nMore.\n"

    assert [chunk.heading for chunk in chunk_markdown(content)] == ["C#", "value###", "value"]


def test_continuation_chunk_context_uses_the_full_heading() -> None:
    content = "# C#\n\n" + "word " * 50 + "\n\n" + "tail " * 50 + "\n"

    chunks = chunk_markdown(content, max_chars=260)

    assert chunks[-1].heading == "C#"
    assert embedding_text(PurePosixPath("Langs.md"), chunks[-1]).startswith("Langs\n\nC#\n\n")
