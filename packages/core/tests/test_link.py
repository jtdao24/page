import dataclasses
from uuid import UUID

import pytest

from page_core.domain import Link

SOURCE_ID = UUID("00000000-0000-0000-0000-000000000010")
TARGET_ID = UUID("00000000-0000-0000-0000-000000000011")


def test_resolved_reference() -> None:
    link = Link(SOURCE_ID, "Project Plan", TARGET_ID)

    assert link.source_note_id == SOURCE_ID
    assert link.target_reference == "Project Plan"
    assert link.target_note_id == TARGET_ID


def test_unresolved_reference_defaults_to_no_target() -> None:
    link = Link(SOURCE_ID, "Not Written Yet")

    assert link.target_note_id is None


def test_preserves_original_reference_verbatim() -> None:
    reference = " projects/Plan#Goals|our goals "

    assert Link(SOURCE_ID, reference).target_reference == reference


@pytest.mark.parametrize("reference", ["", " ", "\t\n"])
def test_rejects_empty_target_reference(reference: str) -> None:
    with pytest.raises(ValueError, match="target_reference"):
        Link(SOURCE_ID, reference)


@pytest.mark.parametrize(
    "args",
    [
        (str(SOURCE_ID), "Project Plan", None),
        (None, "Project Plan", None),
        (SOURCE_ID, None, None),
        (SOURCE_ID, b"Project Plan", None),
        (SOURCE_ID, "Project Plan", str(TARGET_ID)),
    ],
)
def test_rejects_incorrect_types(args: tuple[object, object, object]) -> None:
    with pytest.raises(TypeError):
        Link(*args)  # type: ignore[arg-type]


def test_fields_are_immutable() -> None:
    link = Link(SOURCE_ID, "Project Plan")

    with pytest.raises(dataclasses.FrozenInstanceError):
        link.target_note_id = TARGET_ID  # type: ignore[misc]
