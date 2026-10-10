"""Real FAISS indexing and source fidelity, with offline embeddings for mechanics."""
import re
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import uuid4

import pytest

from page_core.domain import Note
from page_core.metadata import PersistentVault
from page_core.semantic import (EmbeddingError, IndexCorruptError, SemanticIndex, SentenceEncoder,
                                split_note)


class CountingEncoder:
    fingerprint = "test-encoder-v1"
    dimension = 3

    def __init__(self):
        self.calls = []
        self.fail = False

    def offsets(self, text):
        return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]

    def encode(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise EmbeddingError("test failure")
        return [[float('fruit' in text), float('space' in text), 0.1] for text in texts]


def source(text):
    now = datetime.now(UTC)
    return Note(uuid4(), uuid4(), PurePosixPath('日本語.md'), text, now, now)


def test_chunks_preserve_bytes_unicode_crlf_identity_and_duplicates():
    encoder = CountingEncoder()
    note = source('\ufeff# Heading\r\n\r\n日本語 😀 fruit\r\n\r\nfruit fruit\r\n\r\nfruit fruit\r\n\r\n')
    chunks = split_note(note, encoder.offsets, 2)
    raw = note.content.encode()
    for chunk in chunks:
        assert raw[chunk.start_byte:chunk.end_byte].decode() == chunk.text
        assert chunk.token_count <= 2
        assert chunk.note_id == note.id
    assert len({c.id for c in chunks}) == len(chunks)
    assert chunks == split_note(note, encoder.offsets, 2)
    moved = replace(note, relative_path=PurePosixPath('nested/moved.md'))
    assert split_note(moved, encoder.offsets, 2) == chunks
    inserted = replace(note, content='new paragraph\r\n\r\n'+note.content)
    assert {c.id for c in chunks} <= {c.id for c in split_note(inserted, encoder.offsets, 2)}
    assert split_note(source(' \r\n\t'), encoder.offsets) == ()


@pytest.mark.parametrize('value,exception', [(True, TypeError), ('3', TypeError), (0, ValueError)])
def test_chunk_bounds(value, exception):
    with pytest.raises(exception):
        split_note(source('text'), CountingEncoder().offsets, value)


def test_incremental_reopen_move_delete_failure_and_rebuild(tmp_path):
    encoder = CountingEncoder()
    with PersistentVault.create(tmp_path/'vault', 'Search') as storage:
        a = storage.create_note(PurePosixPath('a.md'), 'fruit apples\n\nfruit pears\n\n')
        b = storage.create_note(PurePosixPath('b.md'), 'space stars')
        index = SemanticIndex(storage.metadata, encoder)
        report = index.update((a, b))
        assert (report.generated, report.reused, report.chunks) == (3, 0, 3)
        assert index.update((a, b)).generated == 0
        hits = index.search('fruit', (a, b), {a.id:'a'*64, b.id:'b'*64}, 2)
        assert all(hit.chunk.note_id == a.id for hit in hits)
        assert index.search('fruit', (b, a), {a.id:'a'*64, b.id:'b'*64}, 2) == hits
        moved = storage.move_note(a, PurePosixPath('nested/a.md'))
        assert index.update((moved, b)).generated == 0
        changed = storage.update_note(moved, 'fruit apples\n\nspace planets\n\n')
        report = index.update((changed, b))
        assert (report.generated, report.reused, report.removed) == (1, 2, 1)
        before = storage.metadata.read_vectors(encoder.fingerprint)
        encoder.fail = True
        changed = storage.update_note(changed, 'brand new content')
        with pytest.raises(EmbeddingError):
            index.update((changed, b))
        assert storage.metadata.read_vectors(encoder.fingerprint) == before
        encoder.fail = False
        assert index.update((changed, b)).generated == 1
        root = storage.vault.root_path
    with PersistentVault.open(root) as reopened:
        notes = tuple(reopened.read_note(record.relative_path) for record in reopened.metadata.list_notes())
        index = SemanticIndex(reopened.metadata, encoder)
        assert index.update(notes).generated == 0
        with reopened.metadata.transaction():
            reopened.metadata._db.execute("UPDATE semantic_vectors SET vector=?", (b'bad',))
        with pytest.raises(IndexCorruptError):
            index.update(notes)
        assert index.update(notes, rebuild=True).generated == 2
        assert index.update(()).removed == 2
        assert index.search('fruit', (), {}) == ()


def test_invalid_vectors_are_atomic(tmp_path):
    encoder = CountingEncoder()
    with PersistentVault.create(tmp_path/'vault', 'Search') as storage:
        note = storage.create_note(PurePosixPath('a.md'), 'fruit')
        encoder.encode = lambda texts: [[float('nan'), 1, 0]]
        with pytest.raises(EmbeddingError):
            SemanticIndex(storage.metadata, encoder).update((note,))
        assert storage.metadata.read_vectors(encoder.fingerprint) == {}


@pytest.mark.parametrize('query,limit,exception', [('',10,ValueError), ('x'*2001,10,ValueError),
    ('fruit',0,ValueError), ('fruit',51,ValueError), ('fruit',True,TypeError), (1,10,TypeError)])
def test_invalid_search_inputs(tmp_path, query, limit, exception):
    with PersistentVault.create(tmp_path/'vault', 'Search') as storage:
        with pytest.raises(exception):
            SemanticIndex(storage.metadata, CountingEncoder()).search(query, (), {}, limit)


def test_real_pretrained_relevance_and_source_attribution(tmp_path):
    # Explicitly opt in after prepare-model; mechanics tests never require a
    # network connection or substitute fake vectors for relevance evidence.
    import os
    if os.environ.get('PAGE_TEST_SEMANTIC_MODEL') != '1':
        pytest.skip('run PAGE_TEST_SEMANTIC_MODEL=1 after prepare-model for real model acceptance')
    encoder = SentenceEncoder()
    with PersistentVault.create(tmp_path/'vault', 'Meaning') as storage:
        texts = {
            'garden.md': 'Seedlings require moist soil and sunlight. Water the young plants regularly.',
            'database.md': 'An SQL transaction commits all changes together or rolls back on failure.',
            'astronomy.md': 'Earth orbits the Sun. The Moon is a natural satellite of our planet.',
            'cooking.md': 'Bake bread with flour, yeast and water. Knead the dough before baking.',
        }
        notes = tuple(storage.create_note(PurePosixPath(path), text) for path, text in texts.items())
        index = SemanticIndex(storage.metadata, encoder)
        cases = [('How do I care for baby vegetables?', 'garden.md'),
                 ('How can writes be all or nothing?', 'database.md'),
                 ('What circles our world in space?', 'astronomy.md'),
                 ('How do I make a loaf?', 'cooking.md')]
        for query, expected in cases:
            hits = index.search(query, notes, {n.id:'a'*64 for n in notes}, 1)
            assert str(hits[0].relative_path) == expected
            assert hits[0].chunk.text == texts[expected]
        assert index.update(notes).reused == 4
        long_note = source('日本語😀 '+('verylongword '*600))
        chunks = split_note(long_note, encoder.offsets)
        assert len(chunks) > 1
        assert all(len(encoder.offsets(chunk.text)) <= 254 for chunk in chunks)
        assert all(long_note.content.encode()[c.start_byte:c.end_byte].decode() == c.text for c in chunks)


@pytest.mark.parametrize('separator', ['\n', '\r\n', '\r'])
def test_heading_boundaries_with_each_source_line_ending(separator):
    note = source('intro'+separator+'# Heading'+separator+'body')
    chunks = split_note(note, CountingEncoder().offsets)
    assert [chunk.text for chunk in chunks] == ['intro'+separator, '# Heading'+separator+'body']


def test_fingerprint_invalidates_vectors_and_failed_sql_rolls_back(tmp_path):
    import sqlite3
    encoder = CountingEncoder()
    with PersistentVault.create(tmp_path/'vault', 'Search') as storage:
        note = storage.create_note(PurePosixPath('a.md'), 'fruit')
        index = SemanticIndex(storage.metadata, encoder)
        index.update((note,))
        encoder.fingerprint = 'changed-model-v2'
        assert index.update((note,)).generated == 1
        before = storage.metadata.read_vectors(encoder.fingerprint)
        with pytest.raises(sqlite3.IntegrityError):
            storage.metadata.replace_vectors(encoder.fingerprint, [(uuid4(), uuid4(), b'bad')])
        assert storage.metadata.read_vectors(encoder.fingerprint) == before


def test_search_line_ranges_match_for_each_line_ending(tmp_path):
    ranges = {}
    for name, separator in (('lf', '\n'), ('crlf', '\r\n'), ('cr', '\r')):
        encoder = CountingEncoder()
        text = separator.join(['intro', '', 'fruit apples', 'fruit pears', '', 'space stars', ''])
        with PersistentVault.create(tmp_path/name, 'Lines') as storage:
            note = storage.create_note(PurePosixPath('n.md'), text)
            index = SemanticIndex(storage.metadata, encoder)
            index.update((note,))
            hits = index.search('fruit', (note,), {note.id: 'a'*64}, 10)
            ranges[name] = sorted((hit.start_line, hit.end_line) for hit in hits)
    assert ranges['crlf'] == ranges['lf'] == ranges['cr']
