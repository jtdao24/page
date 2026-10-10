import dataclasses
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from uuid import UUID

import pytest

from page_core.domain import Note

NOTE_ID = UUID("00000000-0000-0000-0000-000000000010")
VAULT_ID = UUID("00000000-0000-0000-0000-000000000001")
CREATED = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
UPDATED = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)


def make_note(**overrides: object) -> Note:
    fields: dict[str, object] = {
        "id": NOTE_ID,
        "vault_id": VAULT_ID,
        "relative_path": PurePosixPath("projects/page/plan.md"),
        "content": "# Plan\n",
        "created_at": CREATED,
        "updated_at": UPDATED,
    }
    fields.update(overrides)
    return Note(**fields)  # type: ignore[arg-type]


def test_valid_note() -> None:
    note = make_note()

    assert note.id == NOTE_ID
    assert note.vault_id == VAULT_ID
    assert note.relative_path == PurePosixPath("projects/page/plan.md")
    assert note.content == "# Plan\n"
    assert note.created_at == CREATED
    assert note.updated_at == UPDATED


def test_allows_empty_content() -> None:
    assert make_note(content="").content == ""


def test_allows_equal_timestamps() -> None:
    assert make_note(updated_at=CREATED).updated_at == CREATED


def test_allows_non_utc_timezones() -> None:
    offset = timezone(timedelta(hours=-5))
    note = make_note(
        created_at=datetime(2026, 1, 1, 4, 0, tzinfo=offset),
        updated_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
    )

    assert note.updated_at == note.created_at


def test_identity_is_independent_of_path() -> None:
    note = make_note()
    moved = dataclasses.replace(note, relative_path=PurePosixPath("archive/plan-v1.md"))

    assert moved.id == note.id
    assert moved.relative_path != note.relative_path


@pytest.mark.parametrize("path", ["/plan.md", "/projects/plan.md", "//plan.md"])
def test_rejects_absolute_path(path: str) -> None:
    with pytest.raises(ValueError, match="relative"):
        make_note(relative_path=PurePosixPath(path))


@pytest.mark.parametrize("path", ["../plan.md", "projects/../plan.md", "a/b/../../c.md"])
def test_rejects_parent_traversal(path: str) -> None:
    with pytest.raises(ValueError, match=r"\.\."):
        make_note(relative_path=PurePosixPath(path))


def test_rejects_empty_path() -> None:
    with pytest.raises(ValueError, match="empty"):
        make_note(relative_path=PurePosixPath(""))


@pytest.mark.parametrize(
    "path", ["plan", "plan.txt", "plan.MD", "plan.md.bak", ".md", "projects/.md"]
)
def test_rejects_non_markdown_extension(path: str) -> None:
    with pytest.raises(ValueError, match=r"\.md"):
        make_note(relative_path=PurePosixPath(path))


@pytest.mark.parametrize(
    "path", ["projects\\plan.md", "C:/projects/plan.md", "plan:draft.md", "plan\x00.md"]
)
def test_rejects_unsafe_path_characters(path: str) -> None:
    with pytest.raises(ValueError, match="must not contain"):
        make_note(relative_path=PurePosixPath(path))


@pytest.mark.parametrize("field", ["created_at", "updated_at"])
def test_rejects_naive_timestamps(field: str) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_note(**{field: datetime(2026, 1, 1, 9, 0)})


def test_rejects_updated_before_created() -> None:
    with pytest.raises(ValueError, match="updated_at"):
        make_note(created_at=UPDATED, updated_at=CREATED)


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": str(NOTE_ID)},
        {"vault_id": None},
        {"relative_path": "projects/page/plan.md"},
        {"relative_path": Path("projects/page/plan.md")},
        {"relative_path": PureWindowsPath("projects/page/plan.md")},
        {"content": None},
        {"content": b"# Plan\n"},
        {"created_at": "2026-01-01T09:00:00+00:00"},
        {"updated_at": date(2026, 1, 2)},
    ],
)
def test_rejects_incorrect_types(overrides: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        make_note(**overrides)


def test_fields_are_immutable() -> None:
    note = make_note()

    with pytest.raises(dataclasses.FrozenInstanceError):
        note.content = "changed"  # type: ignore[misc]
