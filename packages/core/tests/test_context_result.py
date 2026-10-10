import dataclasses
from uuid import UUID

import pytest

from page_core.domain import Chunk, ContextResult

NOTE_ID = UUID("00000000-0000-0000-0000-000000000010")
FIRST = Chunk(UUID("00000000-0000-0000-0000-000000000100"), NOTE_ID, 0, "Alpha", 0, 5, 1)
SECOND = Chunk(UUID("00000000-0000-0000-0000-000000000101"), NOTE_ID, 1, "Beta", 6, 10, 1)


def make_result(**overrides: object) -> ContextResult:
    fields: dict[str, object] = {
        "context_text": "Alpha\nBeta",
        "selected_chunks": (FIRST, SECOND),
        "token_count": 3,
        "token_budget": 100,
    }
    fields.update(overrides)
    return ContextResult(**fields)  # type: ignore[arg-type]


def test_valid_context() -> None:
    result = make_result()

    assert result.context_text == "Alpha\nBeta"
    assert result.selected_chunks == (FIRST, SECOND)
    assert result.selected_chunks[0] is FIRST
    assert result.token_count == 3
    assert result.token_budget == 100


def test_empty_result() -> None:
    result = make_result(context_text="", selected_chunks=(), token_count=0)

    assert result.selected_chunks == ()
    assert result.token_count == 0


def test_allows_token_count_equal_to_budget() -> None:
    assert make_result(token_count=100).token_count == 100


def test_selected_chunks_are_immutable() -> None:
    result = make_result()

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.selected_chunks = ()  # type: ignore[misc]
    with pytest.raises(TypeError):
        result.selected_chunks[0] = SECOND  # type: ignore[index]


def test_rejects_mutable_chunk_list() -> None:
    with pytest.raises(TypeError, match="tuple"):
        make_result(selected_chunks=[FIRST, SECOND])


@pytest.mark.parametrize("budget", [0, -1])
def test_rejects_non_positive_token_budget(budget: int) -> None:
    with pytest.raises(ValueError, match="token_budget"):
        make_result(token_count=0, token_budget=budget)


def test_rejects_negative_token_count() -> None:
    with pytest.raises(ValueError, match="token_count"):
        make_result(token_count=-1)


def test_rejects_token_count_exceeding_budget() -> None:
    with pytest.raises(ValueError, match="exceeds"):
        make_result(token_count=101, token_budget=100)


@pytest.mark.parametrize(
    "overrides",
    [
        {"context_text": None},
        {"context_text": b"Alpha"},
        {"selected_chunks": None},
        {"selected_chunks": (FIRST, "Beta")},
        {"token_count": "3"},
        {"token_count": True},
        {"token_budget": 100.0},
        {"token_budget": None},
    ],
)
def test_rejects_incorrect_types(overrides: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        make_result(**overrides)
