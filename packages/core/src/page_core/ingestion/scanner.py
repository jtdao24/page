"""Read snapshots through directory descriptors; never follow note symlinks."""

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from page_core.vault import _is_managed_path


@dataclass(frozen=True)
class Document:
    path: PurePosixPath
    content: str
    digest: str
    device: int
    inode: int
    mtime_ns: int


def scan(root: Path, *, max_bytes: int = 16 * 1024 * 1024) -> list[Document]:
    """Hash all managed files, so same-size/mtime edits are detected too.

    A read error aborts the scan, preventing transient errors becoming deletions.
    Hidden entries, nonportable paths, symlinks and special files are skipped.
    Requires POSIX directory descriptors (macOS/Linux).
    """
    if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise RuntimeError("secure ingestion requires POSIX directory descriptors")
    result: list[Document] = []
    flags = os.O_RDONLY | os.O_NOFOLLOW

    def walk(directory: int, prefix: tuple[str, ...]) -> None:
        for name in sorted(os.listdir(directory)):
            if name.startswith("."):
                continue
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            parts = (*prefix, name)
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, flags | os.O_DIRECTORY, dir_fd=directory)
                try:
                    walk(child, parts)
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode) and _is_managed_path(PurePosixPath(*parts)):
                descriptor = os.open(name, flags | os.O_NONBLOCK, dir_fd=directory)
                with os.fdopen(descriptor, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise ValueError(f"not a regular note: {parts}")
                    raw = stream.read(max_bytes + 1)
                    after = os.fstat(stream.fileno())
                if len(raw) > max_bytes:
                    raise ValueError(f"note exceeds {max_bytes} bytes: {parts}")
                if (before.st_mtime_ns, before.st_ctime_ns, before.st_size) != (
                    after.st_mtime_ns, after.st_ctime_ns, after.st_size
                ):
                    raise RuntimeError(f"note changed during scan: {parts}")
                result.append(Document(
                    PurePosixPath(*parts), raw.decode("utf-8"),
                    hashlib.sha256(raw).hexdigest(), after.st_dev, after.st_ino,
                    after.st_mtime_ns,
                ))

    descriptor = os.open(root, flags | os.O_DIRECTORY)
    try:
        walk(descriptor, ())
    finally:
        os.close(descriptor)
    return result
