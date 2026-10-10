import dataclasses
from uuid import UUID

import pytest

from page_core.domain import Chunk

CHUNK_ID = UUID("00000000-0000-0000-0000-000000000100")
NOTE_ID = UUID("00000000-0000-0000-0000-000000000010")


def make_chunk(**overrides: object) -> Chunk:
    fields: dict[str, object] = {
        "id": CHUNK_ID,
        "note_id": NOTE_ID,
        "ordinal": 0,
        "text": "café",
        "start_byte": 10,
        "end_byte": 15,
    }
    fields.update(overrides)
    return Chunk(**fields)  # type: ignore[arg-type]


def test_valid_source_offsets() -> None:
    chunk = make_chunk(token_count=2)

    assert chunk.note_id == NOTE_ID
    assert chunk.ordinal == 0
    assert (chunk.start_byte, chunk.end_byte) == (10, 15)
    # Offsets are UTF-8 bytes: "café" is 4 characters but 5 bytes.
    assert chunk.end_byte - chunk.start_byte == len(chunk.text.encode("utf-8"))
    assert chunk.token_count == 2


def test_allows_offsets_starting_at_zero() -> None:
    assert make_chunk(start_byte=0, end_byte=1, text="a").start_byte == 0


def test_token_count_is_optional() -> None:
    assert make_chunk().token_count is None


def test_allows_zero_token_count() -> None:
    assert make_chunk(token_count=0).token_count == 0


@pytest.mark.parametrize(("start", "end"), [(10, 10), (15, 10)])
def test_rejects_invalid_offset_ordering(start: int, end: int) -> None:
    with pytest.raises(ValueError, match="end_byte"):
        make_chunk(start_byte=start, end_byte=end)


@pytest.mark.parametrize("field", ["start_byte", "end_byte"])
def test_rejects_negative_offsets(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        make_chunk(**{field: -1})


def test_rejects_negative_ordinal() -> None:
    with pytest.raises(ValueError, match="ordinal"):
        make_chunk(ordinal=-1)


def test_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="text"):
        make_chunk(text="")


def test_rejects_negative_token_count() -> None:
    with pytest.raises(ValueError, match="token_count"):
        make_chunk(token_count=-1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": str(CHUNK_ID)},
        {"note_id": None},
        {"ordinal": 1.0},
        {"ordinal": True},
        {"text": None},
        {"text": b"cafe"},
        {"start_byte": "10"},
        {"end_byte": 15.0},
        {"token_count": 2.0},
        {"token_count": False},
        {"token_count": "2"},
    ],
)
def test_rejects_incorrect_types(overrides: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        make_chunk(**overrides)


def test_fields_are_immutable() -> None:
    chunk = make_chunk()

    with pytest.raises(dataclasses.FrozenInstanceError):
        chunk.text = "changed"  # type: ignore[misc]
