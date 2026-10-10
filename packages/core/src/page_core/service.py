"""Index the Markdown vault and keep SQLite relationship metadata in sync."""

from __future__ import annotations

from pathlib import Path

from page_core.store import GraphPayload, LinkStore
from page_core.vault import NoteRecord, Vault
from page_core.wiki_links import NoteRef, resolve_links


class KnowledgeService:
    def __init__(self, vault_path: Path) -> None:
        self.vault = Vault(vault_path)
        self.store = LinkStore(self.vault.db_path())
        self.reindex()

    def close(self) -> None:
        self.store.close()

    def _refs(self) -> list[NoteRef]:
        return [
            NoteRef(id=note.id, title=note.title, path=note.path)
            for note in self.vault.list_notes()
        ]

    def reindex(self) -> None:
        refs = self._refs()
        links_by_source = {}
        for note in self.vault.list_notes():
            record = self.vault.read(note.id)
            links_by_source[note.id] = resolve_links(record.content, refs)
        self.store.replace_vault(refs, links_by_source)

    def list_notes(self) -> list[NoteRecord]:
        return self.vault.list_notes()

    def get_note(self, note_id: str) -> NoteRecord:
        return self.vault.read(note_id)

    def create_note(self, title: str, content: str = "") -> NoteRecord:
        note = self.vault.create(title, content)
        self.reindex()
        return self.vault.read(note.id)

    def update_note(self, note_id: str, content: str, title: str | None = None) -> NoteRecord:
        note = self.vault.write(note_id, content, title)
        self.reindex()
        return self.vault.read(note.id)

    def delete_note(self, note_id: str) -> None:
        self.vault.delete(note_id)
        self.reindex()

    def backlinks(self, note_id: str) -> list:
        self.vault.read(note_id)
        return self.store.backlinks(note_id)

    def graph(self) -> GraphPayload:
        return self.store.graph()
