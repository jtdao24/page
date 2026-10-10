import os
from collections.abc import Callable, Iterator
from itertools import count
from pathlib import Path
from uuid import UUID

import pytest

from page_core.vault import FileSystemVault


@pytest.fixture
def id_factory() -> Callable[[], UUID]:
    counter = count(1)
    return lambda: UUID(int=next(counter))


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    return tmp_path / "vault"


@pytest.fixture
def fs_vault(vault_root: Path, id_factory: Callable[[], UUID]) -> FileSystemVault:
    return FileSystemVault.create(vault_root, "Research", id_factory=id_factory)


@pytest.fixture
def symlinks(tmp_path: Path) -> Iterator[None]:
    """Skip the test where the platform or user cannot create symlinks."""
    probe = tmp_path / "symlink-probe"
    try:
        os.symlink(tmp_path, probe)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not supported here")
    probe.unlink()
    yield


@pytest.fixture
def hardlinks(tmp_path: Path) -> Iterator[None]:
    """Skip the test where the filesystem cannot create hard links."""
    source = tmp_path / "hardlink-source"
    source.touch()
    try:
        os.link(source, tmp_path / "hardlink-probe")
    except (OSError, NotImplementedError):
        pytest.skip("hard links are not supported here")
    (tmp_path / "hardlink-probe").unlink()
    source.unlink()
    yield


@pytest.fixture
def case_insensitive(tmp_path: Path) -> bool:
    (tmp_path / "case-probe").touch()
    return (tmp_path / "CASE-PROBE").exists()


def snapshot(root: Path) -> dict[str, bytes]:
    """Every regular file under ``root`` (including hidden ones) and its bytes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }
