"""Local Markdown vault: notes are files the user owns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass(frozen=True)
class NoteRecord:
    id: str
    title: str
    path: str
    content: str


class VaultError(ValueError):
    """Invalid vault path or note identifier."""


def sanitize_filename(title: str) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("-", title.strip())
    cleaned = cleaned.strip(" .")
    return cleaned or "Untitled"


def title_from_path(relative: Path) -> str:
    return relative.stem


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".page").mkdir(parents=True, exist_ok=True)

    def db_path(self) -> Path:
        return self.root / ".page" / "links.sqlite"

    def _relative(self, note_id: str) -> Path:
        relative = Path(note_id.replace("\\", "/"))
        if relative.is_absolute() or ".." in relative.parts:
            raise VaultError("Note path must stay inside the vault.")
        if relative.suffix.lower() != ".md":
            raise VaultError("Notes must be Markdown files.")
        full = (self.root / relative).resolve()
        try:
            full.relative_to(self.root)
        except ValueError as exc:
            raise VaultError("Note path must stay inside the vault.") from exc
        return relative

    def _skip(self, relative: Path) -> bool:
        return any(part.startswith(".") for part in relative.parts)

    def list_notes(self) -> list[NoteRecord]:
        notes: list[NoteRecord] = []
        for path in sorted(self.root.rglob("*.md")):
            relative = path.relative_to(self.root)
            if self._skip(relative):
                continue
            posix = relative.as_posix()
            notes.append(
                NoteRecord(
                    id=posix,
                    title=title_from_path(relative),
                    path=posix,
                    content="",
                )
            )
        return notes

    def read(self, note_id: str) -> NoteRecord:
        relative = self._relative(note_id)
        path = self.root / relative
        if not path.is_file():
            raise FileNotFoundError(note_id)
        return NoteRecord(
            id=relative.as_posix(),
            title=title_from_path(relative),
            path=relative.as_posix(),
            content=path.read_text(encoding="utf-8"),
        )

    def unique_relative(self, title: str, exclude_id: str | None = None) -> Path:
        base = sanitize_filename(title)
        candidate = Path(f"{base}.md")
        index = 2
        while True:
            posix = candidate.as_posix()
            if posix != exclude_id and not (self.root / candidate).exists():
                return candidate
            candidate = Path(f"{base} {index}.md")
            index += 1

    def create(self, title: str, content: str = "") -> NoteRecord:
        relative = self.unique_relative(title)
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return self.read(relative.as_posix())

    def write(self, note_id: str, content: str, title: str | None = None) -> NoteRecord:
        current = self.read(note_id)
        relative = self._relative(note_id)
        path = self.root / relative
        next_relative = relative
        if title is not None and sanitize_filename(title) != current.title:
            next_relative = self.unique_relative(title, exclude_id=current.id)
            next_path = self.root / next_relative
            next_path.parent.mkdir(parents=True, exist_ok=True)
            path.replace(next_path)
            path = next_path
        path.write_text(content, encoding="utf-8")
        return self.read(next_relative.as_posix())

    def delete(self, note_id: str) -> None:
        relative = self._relative(note_id)
        path = self.root / relative
        if not path.is_file():
            raise FileNotFoundError(note_id)
        path.unlink()
