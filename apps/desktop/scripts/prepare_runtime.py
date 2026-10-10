"""Build the Python runtime bundled into the packaged Page app.

Produces ``apps/desktop/src-tauri/runtime/``, which ``tauri.bundle.conf.json``
copies into the app's resources:

    python/       relocatable CPython 3.12 (python-build-standalone) with Page
                  Core and its locked dependencies, precompiled
    model/        the pinned embedding model as a plain folder (PAGE_MODEL_DIR)
    bin/page-mcp  launcher for Page's MCP server (macOS)

Run with the development interpreter from the repository root:

    .venv/bin/python apps/desktop/scripts/prepare_runtime.py [--sign IDENTITY]

Downloads are pinned and verified by SHA-256. Wheels only: nothing is compiled.
"""

import argparse
import hashlib
import os
import platform
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "apps" / "desktop" / "src-tauri" / "runtime"
ENTITLEMENTS = ROOT / "apps" / "desktop" / "src-tauri" / "runtime-entitlements.plist"
LOCK = ROOT / "packages" / "core" / "requirements-dev.txt"

RELEASE = "20261009"
PYTHON = "3.12.15"
URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/"
       f"{RELEASE}/cpython-{PYTHON}+{RELEASE}-{{target}}-install_only_stripped.tar.gz")
SHA256 = {
    "aarch64-apple-darwin": "233f8e15255b3e1d1fd47ea5dd5230dfed803f371138e896e54d98c60ae19f6f",
    "x86_64-apple-darwin": "fb3187d95334813b88940db0f1ca57b84cedfd552739c3a5771c3ea0e49988c9",
    "x86_64-pc-windows-msvc": "11ed9f8a6ac64fb1b5a55e40e305a6744a3f77a70863c8f8197a6e4349abc64a",
}
# Offline model loading from the bundled folder. Rust sets the same variables.
OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}

MCP_LAUNCHER = """#!/bin/sh
# Page's MCP server with the bundled runtime: page-mcp --vault /path/to/vault
runtime=$(cd "$(dirname "$0")/.." && pwd -P)
export PAGE_MODEL_DIR="$runtime/model" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
exec "$runtime/python/bin/python3" -I -B -m page_core.mcp_server "$@"
"""


def host_target() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        return "aarch64-apple-darwin" if machine == "arm64" else "x86_64-apple-darwin"
    if sys.platform == "win32" and machine in ("amd64", "x86_64"):
        return "x86_64-pc-windows-msvc"
    raise SystemExit(f"unsupported build host: {sys.platform} {machine}")


def run(*args: str | Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], check=True, env=env)


def download(target: str, cache: Path) -> Path:
    url = URL.format(target=target)
    archive = cache / url.rsplit("/", 1)[1]
    if not archive.exists():
        print(f"downloading {url}", flush=True)
        partial = archive.with_suffix(".partial")
        import certifi  # python.org builds on macOS ship no CA certificates
        context = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(url, timeout=120, context=context) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.rename(archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != SHA256[target]:
        archive.unlink()
        raise SystemExit(f"checksum mismatch for {archive.name}")
    return archive


def interpreter(python_root: Path) -> Path:
    return python_root / ("python.exe" if os.name == "nt" else "bin/python3")


def site_packages(python_root: Path) -> Path:
    return python_root / ("Lib" if os.name == "nt" else "lib/python3.12") / "site-packages"


def prune(python_root: Path) -> None:
    """Drop files the app never uses at run time."""
    for pattern in ("**/__pycache__", "**/tests", "**/test"):
        for path in list(site_packages(python_root).glob(pattern)):
            if path.is_dir():
                shutil.rmtree(path)
    torch = site_packages(python_root) / "torch"
    for name in ("include", "share"):  # C++ headers and CMake files
        shutil.rmtree(torch / name, ignore_errors=True)
    stdlib = site_packages(python_root).parent
    for name in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3"):
        shutil.rmtree(stdlib / name, ignore_errors=True)


def is_macho(path: Path) -> bool:
    with path.open("rb") as handle:
        magic = handle.read(4)
    return magic in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")


def sign(runtime: Path, identity: str) -> None:
    """Sign every Mach-O file. A Developer ID gets the hardened runtime and a
    timestamp, as notarization requires. Ad hoc ("-") signatures have no Team ID,
    so the hardened runtime's library validation would reject the bundled
    libraries; ad hoc builds are for local testing and are signed without it."""
    files = [path for path in runtime.rglob("*") if path.is_file() and not path.is_symlink() and is_macho(path)]
    hardened = [] if identity == "-" else ["--timestamp", "--options", "runtime"]
    for path in sorted(files, key=lambda item: len(item.parts), reverse=True):
        run("codesign", "--force", *hardened, "--entitlements", ENTITLEMENTS, "--sign", identity, path)
    print(f"signed {len(files)} Mach-O files", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sign", metavar="IDENTITY",
                        help="codesign identity for macOS notarization ('-' for ad hoc)")
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache" / "runtime",
                        help="download cache (default: .cache/runtime)")
    args = parser.parse_args()
    target = host_target()
    args.cache.mkdir(parents=True, exist_ok=True)
    archive = download(target, args.cache)

    if OUTPUT.exists():
        shutil.rmtree(OUTPUT)
    OUTPUT.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        tar.extractall(OUTPUT, filter="data")  # unpacks to python/
    python_root = OUTPUT / "python"
    python = interpreter(python_root)

    with tempfile.TemporaryDirectory() as wheels:
        run(sys.executable, "-m", "pip", "wheel", "--no-deps", "--quiet", "--wheel-dir", wheels,
            ROOT / "packages" / "core")
        (wheel,) = Path(wheels).glob("page_core-*.whl")
        run(python, "-I", "-m", "pip", "install", "--quiet", "--no-cache-dir", "--no-compile",
            "--only-binary=:all:", "--constraint", LOCK, wheel)

    with tempfile.TemporaryDirectory() as cache:
        env = {**os.environ, "HF_HUB_CACHE": cache, "HF_HUB_DISABLE_TELEMETRY": "1"}
        run(python, "-I", "-m", "page_core.semantic", "prepare-model", env=env)
        run(python, "-I", "-m", "page_core.semantic", "export-model", OUTPUT / "model", env=env)
    # pip is only needed to build the runtime.
    run(python, "-I", "-m", "pip", "uninstall", "--quiet", "--yes", "pip")

    prune(python_root)
    # Bytecode is written once here; the signed app never writes inside itself.
    run(python, "-I", "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "unchecked-hash",
        python_root)

    if os.name != "nt":
        launcher = OUTPUT / "bin" / "page-mcp"
        launcher.parent.mkdir()
        launcher.write_text(MCP_LAUNCHER, encoding="utf-8")
        launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Smoke test exactly as the app runs it: isolated, offline, no bytecode writes.
    check = ("import page_core.api, page_core.mcp_server\n"
             "from page_core.semantic import SentenceEncoder\n"
             "print(len(SentenceEncoder().encode(['page'])[0]))\n")
    run(python, "-I", "-B", "-c", check, env={**os.environ, **OFFLINE_ENV, "PAGE_MODEL_DIR": str(OUTPUT / "model")})

    if args.sign:
        if sys.platform != "darwin":
            raise SystemExit("--sign is for macOS")
        sign(OUTPUT, args.sign)
    size = sum(path.stat().st_size for path in OUTPUT.rglob("*") if path.is_file() and not path.is_symlink())
    print(f"runtime ready: {OUTPUT} ({size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
