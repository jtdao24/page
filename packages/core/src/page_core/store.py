"""SQLite index of wiki-link relationships derived from the Markdown vault."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from page_core.wiki_links import NoteRef, ResolvedLink


@dataclass(frozen=True)
class BacklinkRecord:
    source_id: str
    source_title: str
    excerpt: str
    target_title: str


@dataclass(frozen=True)
class GraphPayload:
    nodes: list[dict[str, str]]
    edges: list[dict[str, str]]


class LinkStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                path TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT,
                target_title TEXT NOT NULL,
                raw TEXT NOT NULL,
                excerpt TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES notes(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_id);
            CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id);
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def replace_vault(self, notes: list[NoteRef], links_by_source: dict[str, list[ResolvedLink]]) -> None:
        self._conn.execute("DELETE FROM links")
        self._conn.execute("DELETE FROM notes")
        self._conn.executemany(
            "INSERT INTO notes (id, title, path) VALUES (?, ?, ?)",
            [(note.id, note.title, note.path) for note in notes],
        )
        rows = [
            (source_id, link.target_id, link.title, link.raw, link.excerpt)
            for source_id, links in links_by_source.items()
            for link in links
        ]
        self._conn.executemany(
            """
            INSERT INTO links (source_id, target_id, target_title, raw, excerpt)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        self._conn.commit()

    def backlinks(self, note_id: str) -> list[BacklinkRecord]:
        rows = self._conn.execute(
            """
            SELECT l.source_id, n.title AS source_title, l.excerpt, l.target_title
            FROM links l
            JOIN notes n ON n.id = l.source_id
            WHERE l.target_id = ?
            GROUP BY l.source_id
            ORDER BY n.title COLLATE NOCASE, l.source_id
            """,
            (note_id,),
        ).fetchall()
        return [
            BacklinkRecord(
                source_id=row["source_id"],
                source_title=row["source_title"],
                excerpt=row["excerpt"],
                target_title=row["target_title"],
            )
            for row in rows
        ]

    def graph(self) -> GraphPayload:
        notes = self._conn.execute(
            "SELECT id, title FROM notes ORDER BY title COLLATE NOCASE, id"
        ).fetchall()
        edges = self._conn.execute(
            """
            SELECT DISTINCT source_id, target_id
            FROM links
            WHERE target_id IS NOT NULL
            ORDER BY source_id, target_id
            """
        ).fetchall()
        return GraphPayload(
            nodes=[{"id": row["id"], "title": row["title"]} for row in notes],
            edges=[{"source": row["source_id"], "target": row["target_id"]} for row in edges],
        )
