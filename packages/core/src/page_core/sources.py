"""Read-only knowledge sources in a vault: PDFs, code and plain text.

Sources are files the user keeps in the vault folder next to their notes. Page
never writes them. Their text is extracted (PDF pages with pypdf, code and text
as UTF-8) and cached in memory by file size, modification time and inode, so
search does not re-extract unchanged files. Identity follows the path.
"""

import hashlib
import io
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid5

from page_core.domain import SourceDocument, source_kind, validate_source_path
from page_core.vault import read_regular_file, require_managed_parts

MAX_SOURCE_BYTES = 25 * 1024 * 1024
MAX_SOURCE_CHARACTERS = 2_000_000
MAX_SOURCES = 5000
# Generated or dependency folders that would drown a vault's own knowledge.
SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__", "venv", "target", "dist", "build"})


class SourceNotFoundError(Exception):
    """No readable source exists at this path."""


class SourceUnreadableError(Exception):
    """The source could not be read or its text extracted."""


@dataclass(frozen=True, slots=True)
class SourceEntry:
    id: UUID
    relative_path: PurePosixPath
    kind: str
    size_bytes: int


def source_id(vault_id: UUID, relative_path: PurePosixPath) -> UUID:
    return uuid5(vault_id, f"source:{relative_path}")


def _is_source_path(relative: PurePosixPath) -> bool:
    try:
        require_managed_parts(validate_source_path(relative))
    except (TypeError, ValueError):
        return False
    return True


def extract_pdf(data: bytes) -> str:
    """Page-by-page text, each page introduced by a ``[Page n]`` marker."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise SourceUnreadableError("the PDF is password-protected")
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(f"[Page {number}]\n{text}")
    except SourceUnreadableError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise SourceUnreadableError("the PDF could not be read") from exc
    return "\n\n".join(pages) + ("\n" if pages else "")


def extract_text(relative_path: PurePosixPath, data: bytes) -> str:
    if source_kind(relative_path) == "pdf":
        text = extract_pdf(data)
    else:
        try:
            text = data.decode("utf-8").removeprefix("﻿")
        except UnicodeDecodeError as exc:
            raise SourceUnreadableError("the file is not UTF-8 text") from exc
    return text[:MAX_SOURCE_CHARACTERS]


class SourceLibrary:
    """Sources in one vault folder, with extracted text cached per file version."""

    def __init__(self, root: Path, vault_id: UUID, *,
                 extract: Callable[[PurePosixPath, bytes], str] = extract_text) -> None:
        if not isinstance(root, Path) or not isinstance(vault_id, UUID):
            raise TypeError("root must be Path and vault_id must be UUID")
        self._root = root
        self._vault_id = vault_id
        self._extract = extract
        self._cache: dict[PurePosixPath, tuple[tuple[int, int, int], SourceDocument | None]] = {}

    def list(self) -> list[SourceEntry]:
        """Every source file, sorted by path. Hidden, symlinked and skipped folders are ignored."""
        entries: list[SourceEntry] = []
        for dirpath, dirnames, filenames in os.walk(self._root):
            directory = Path(dirpath)
            dirnames[:] = sorted(name for name in dirnames if not name.startswith(".")
                                 and name not in SKIPPED_FOLDERS and not (directory / name).is_symlink())
            for filename in sorted(filenames):
                relative = PurePosixPath(*(directory / filename).relative_to(self._root).parts)
                if not _is_source_path(relative):
                    continue
                try:
                    info = os.lstat(directory / filename)
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(info.st_mode) and info.st_size <= MAX_SOURCE_BYTES:
                    entries.append(SourceEntry(source_id(self._vault_id, relative), relative,
                                               source_kind(relative) or "text", info.st_size))
                if len(entries) >= MAX_SOURCES:
                    return sorted(entries, key=lambda entry: str(entry.relative_path))
        return sorted(entries, key=lambda entry: str(entry.relative_path))

    def _load(self, relative: PurePosixPath) -> SourceDocument | None:
        """The document, or None when its text cannot be extracted."""
        full = self._root.joinpath(*relative.parts)
        try:
            info = os.lstat(full)
        except FileNotFoundError:
            raise SourceNotFoundError(str(relative)) from None
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_SOURCE_BYTES:
            raise SourceNotFoundError(str(relative))
        version = (info.st_size, info.st_mtime_ns, info.st_ino)
        cached = self._cache.get(relative)
        if cached is not None and cached[0] == version:
            return cached[1]
        try:
            data, _ = read_regular_file(full)
        except FileNotFoundError:
            raise SourceNotFoundError(str(relative)) from None
        try:
            document: SourceDocument | None = SourceDocument(
                source_id(self._vault_id, relative), self._vault_id, relative,
                self._extract(relative, data), hashlib.sha256(data).hexdigest())
        except SourceUnreadableError:
            document = None
        self._cache[relative] = (version, document)
        return document

    def documents(self) -> tuple[SourceDocument, ...]:
        """Readable sources with their extracted text; unreadable ones are skipped."""
        entries = self.list()
        listed = {entry.relative_path for entry in entries}
        for stale in set(self._cache) - listed:
            del self._cache[stale]
        documents = []
        for entry in entries:
            try:
                document = self._load(entry.relative_path)
            except SourceNotFoundError:
                continue
            if document is not None:
                documents.append(document)
        return tuple(documents)

    def get(self, document_id: UUID) -> SourceDocument:
        for entry in self.list():
            if entry.id == document_id:
                document = self._load(entry.relative_path)
                if document is None:
                    raise SourceUnreadableError(str(entry.relative_path))
                return document
        raise SourceNotFoundError(str(document_id))
