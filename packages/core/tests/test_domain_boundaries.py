import builtins
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID

import pytest

INFRASTRUCTURE_MODULES = [
    "asyncio",
    "faiss",
    "fastapi",
    "http.client",
    "mcp",
    "socket",
    "sqlite3",
    "ssl",
    "subprocess",
    "torch",
    "urllib.request",
]


def test_importing_domain_loads_no_infrastructure() -> None:
    script = (
        "import sys, page_core.domain\n"
        f"print(sorted(set({INFRASTRUCTURE_MODULES!r}) & set(sys.modules)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "[]"


def test_models_are_usable_without_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("domain models must not perform I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    for name in ("stat", "lstat", "listdir", "scandir", "mkdir", "makedirs"):
        monkeypatch.setattr(os, name, forbidden)

    from page_core.domain import Chunk, ContextResult, Link, Note, Vault

    vault_id = UUID("00000000-0000-0000-0000-000000000001")
    note_id = UUID("00000000-0000-0000-0000-000000000010")
    moment = datetime(2026, 1, 1, tzinfo=UTC)

    vault = Vault(vault_id, "Research", Path(Path.cwd().anchor, "missing", "vault"))
    note = Note(note_id, vault.id, PurePosixPath("plan.md"), "Alpha", moment, moment)
    link = Link(note.id, "Unwritten Note")
    chunk = Chunk(UUID(int=100), note.id, 0, "Alpha", 0, 5)
    result = ContextResult("Alpha", (chunk,), 1, 10)

    assert note.vault_id == vault.id
    assert link.source_note_id == note.id
    assert result.selected_chunks[0].note_id == note.id
