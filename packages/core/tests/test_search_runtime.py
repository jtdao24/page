import math
import time
from pathlib import Path, PurePosixPath

import pytest

from embedding_fakes import FailingEmbedder, KeywordEmbedder
from page_core.api import Settings
from page_core.api.app import parse_sync_interval
from page_core.retrieval.runtime import SearchRuntime, validate_sync_interval
from page_core.vault import FileSystemVault

INVALID = [-1, -0.5, math.nan, math.inf, -math.inf, True, "30", None]


@pytest.mark.parametrize("seconds", INVALID)
def test_invalid_sync_intervals_are_rejected(fs_vault: FileSystemVault, seconds: object) -> None:
    with pytest.raises(ValueError, match="sync interval"):
        validate_sync_interval(seconds)
    with pytest.raises(ValueError, match="sync interval"):
        SearchRuntime(fs_vault.vault.root_path, KeywordEmbedder, sync_interval=seconds)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sync interval"):
        Settings(fs_vault.vault.root_path, sync_interval=seconds)  # type: ignore[arg-type]


@pytest.mark.parametrize("text", ["-1", "nan", "inf", "-inf", "soon", ""])
def test_invalid_sync_interval_text_is_rejected(text: str) -> None:
    with pytest.raises(ValueError, match="sync interval"):
        parse_sync_interval(text)


@pytest.mark.parametrize(("value", "expected"), [(0, 0.0), (30, 30.0), (0.5, 0.5)])
def test_valid_sync_intervals(value: float, expected: float) -> None:
    assert validate_sync_interval(value) == expected
    assert parse_sync_interval(str(value)) == expected


def test_environment_interval_is_validated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PAGE_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("PAGE_INDEX_SYNC_INTERVAL", "-5")

    with pytest.raises(ValueError, match="sync interval"):
        Settings.from_env()


def test_manual_sync_recovers_from_a_failed_first_build(fs_vault: FileSystemVault) -> None:
    fs_vault.create_note(PurePosixPath("bread.md"), "Knead the dough and bake sourdough bread.")
    embedder = FailingEmbedder()
    embedder.fail = True
    runtime = SearchRuntime(fs_vault.vault.root_path, lambda: embedder, sync_interval=0)
    runtime.start()
    try:
        assert runtime.wait_until_settled(10)
        assert runtime.status().state == "error"

        embedder.fail = False
        runtime.sync_now()

        status = runtime.status()
        assert status.searchable
        assert status.state == "ready"
        assert status.detail is None
        runtime.search("baking bread", 5)

        # Background syncing resumes after the recovery.
        synced = status.last_sync_at
        fs_vault.create_note(PurePosixPath("garden.md"), "Compost the soil before planting seeds.")
        runtime.request_sync()
        deadline = time.monotonic() + 10
        while runtime.status().last_sync_at == synced and time.monotonic() < deadline:
            time.sleep(0.05)
        assert runtime.status().last_sync_at != synced
    finally:
        runtime.stop()
