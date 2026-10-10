import math
from pathlib import Path

import pytest

from embedding_fakes import KeywordEmbedder
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
