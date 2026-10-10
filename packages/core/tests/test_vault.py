import dataclasses
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

from page_core.domain import Vault

VAULT_ID = UUID("00000000-0000-0000-0000-000000000001")
ROOT = Path(Path.cwd().anchor, "vaults", "research")


def make_vault(**overrides: object) -> Vault:
    fields: dict[str, object] = {"id": VAULT_ID, "name": "Research", "root_path": ROOT}
    fields.update(overrides)
    return Vault(**fields)  # type: ignore[arg-type]


def test_valid_vault() -> None:
    vault = make_vault()

    assert vault.id == VAULT_ID
    assert vault.name == "Research"
    assert vault.root_path == ROOT


def test_identity_is_independent_of_location() -> None:
    vault = make_vault()
    moved = dataclasses.replace(vault, root_path=Path(Path.cwd().anchor, "archive"))

    assert moved.id == vault.id


@pytest.mark.parametrize("name", ["", "   ", "\n\t"])
def test_rejects_empty_name(name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        make_vault(name=name)


def test_rejects_relative_root_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        make_vault(root_path=Path("vaults", "research"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"id": str(VAULT_ID)},
        {"name": None},
        {"name": b"Research"},
        {"root_path": str(ROOT)},
        {"root_path": PurePosixPath("/vaults/research")},
    ],
)
def test_rejects_incorrect_types(overrides: dict[str, object]) -> None:
    with pytest.raises(TypeError):
        make_vault(**overrides)


def test_fields_are_immutable() -> None:
    vault = make_vault()

    with pytest.raises(dataclasses.FrozenInstanceError):
        vault.name = "Renamed"  # type: ignore[misc]
