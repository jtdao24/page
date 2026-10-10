"""Runtime builder: pinned downloads, signing commands and pruning."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def builder():
    path = ROOT / "apps" / "desktop" / "scripts" / "prepare_runtime.py"
    spec = importlib.util.spec_from_file_location("prepare_runtime", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_runtime_download_is_pinned(builder):
    assert set(builder.SHA256) == {"aarch64-apple-darwin", "x86_64-apple-darwin", "x86_64-pc-windows-msvc"}
    assert all(len(digest) == 64 and int(digest, 16) >= 0 for digest in builder.SHA256.values())
    assert builder.URL.startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")


def test_launcher_and_app_use_the_same_offline_model_settings(builder):
    backend = (ROOT / "apps" / "desktop" / "src-tauri" / "src" / "backend.rs").read_text()
    for name in ["PAGE_MODEL_DIR", *builder.OFFLINE_ENV]:
        assert f'"{name}"' in backend and name in builder.MCP_LAUNCHER
    assert '"-I", "-B", "-m", "page_core.api"' in backend and "-I -B -m page_core.mcp_server" in builder.MCP_LAUNCHER


def test_signing_uses_the_hardened_runtime_only_with_a_real_identity(builder, tmp_path, monkeypatch):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "a.so").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 16)
    (tmp_path / "python3").write_bytes(b"\xca\xfe\xba\xbe" + b"\0" * 16)
    (tmp_path / "script.py").write_text("print()")
    (tmp_path / "link.so").symlink_to(tmp_path / "lib" / "a.so")
    commands = []
    monkeypatch.setattr(builder, "run", lambda *args, **kwargs: commands.append([str(arg) for arg in args]))
    builder.sign(tmp_path, "Developer ID Application: Page (TEAM)")
    assert [command[-1] for command in commands] == [str(tmp_path / "lib" / "a.so"), str(tmp_path / "python3")]
    assert all("--options" in command and "--timestamp" in command for command in commands)
    assert all(str(builder.ENTITLEMENTS) in command for command in commands)
    commands.clear()
    builder.sign(tmp_path, "-")
    assert len(commands) == 2 and not any("--options" in command or "--timestamp" in command for command in commands)


def test_prune_removes_tests_and_unused_parts(builder, tmp_path, monkeypatch):
    site = tmp_path / "lib" / "python3.12" / "site-packages"
    for path in ("pkg/tests/t.py", "pkg/__pycache__/x.pyc", "pkg/core.py", "torch/include/a.h",
                 "torch/bin/torch_shm_manager", "torch/lib/libtorch.dylib"):
        (site / path).parent.mkdir(parents=True, exist_ok=True)
        (site / path).write_text("")
    (tmp_path / "lib" / "python3.12" / "tkinter").mkdir()
    monkeypatch.setattr(builder.os, "name", "posix")
    builder.prune(tmp_path)
    assert sorted(str(p.relative_to(site)) for p in site.rglob("*") if p.is_file()) == [
        "pkg/core.py", "torch/bin/torch_shm_manager", "torch/lib/libtorch.dylib"]
    assert not (tmp_path / "lib" / "python3.12" / "tkinter").exists()
