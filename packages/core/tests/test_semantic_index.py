import os
from pathlib import Path, PurePosixPath

import numpy as np
import pytest

from embedding_fakes import KeywordEmbedder
from page_core.embeddings import IndexIncompatibleError, IndexStorageError, SemanticIndex
from page_core.embeddings.index import DB_FILE, FAISS_FILE
from page_core.vault import FileSystemVault

P = PurePosixPath


def _write(vault: FileSystemVault, path: str, content: str) -> None:
    target = vault.vault.root_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8"))


def _bump_mtime(vault: FileSystemVault, path: str) -> None:
    target = vault.vault.root_path / path
    info = os.stat(target)
    os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))


def _query(embedder: KeywordEmbedder, text: str) -> np.ndarray:
    return embedder.embed([text])


@pytest.fixture
def embedder() -> KeywordEmbedder:
    return KeywordEmbedder()


@pytest.fixture
def notes(fs_vault: FileSystemVault) -> FileSystemVault:
    _write(fs_vault, "logic.md", "# Logic\n\nUse a Karnaugh map to minimize boolean gates.\n")
    _write(fs_vault, "baking.md", "# Bread\n\nKnead the dough and let the yeast work.\n")
    _write(fs_vault, "space/orbits.md", "Planets orbit their star.\n")
    return fs_vault


def test_sync_indexes_every_note_into_faiss(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    report = index.sync(notes)

    assert (report.added, report.updated, report.removed) == (3, 0, 0)
    stats = index.stats()
    assert (stats.notes, stats.chunks, stats.metric) == (3, 3, "cosine")
    hits = index.search(_query(embedder, "simplify a digital circuit"), 3)
    assert hits[0].path == P("logic.md")
    assert hits[0].text.startswith("# Logic")
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)
    assert hits[0].score == pytest.approx(
        float(_query(embedder, "simplify a digital circuit")[0] @ embedder.embed(
            ["logic\n\n" + hits[0].text]
        )[0]),
        abs=1e-5,
    )


def test_index_files_live_in_the_hidden_metadata_folder(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    SemanticIndex.for_vault(notes.vault.root_path, embedder).sync(notes)

    folder = notes.vault.root_path / ".page" / "index"
    assert (folder / FAISS_FILE).is_file()
    assert (folder / DB_FILE).is_file()
    assert notes.list_note_paths() == [P("baking.md"), P("logic.md"), P("space/orbits.md")]


def test_unchanged_notes_are_not_re_embedded(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)
    embedder.calls.clear()

    report = index.sync(notes)

    assert (report.added, report.updated, report.unchanged) == (0, 0, 3)
    assert embedder.calls == []


def test_touched_but_identical_note_is_not_re_embedded(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)
    embedder.calls.clear()
    _bump_mtime(notes, "logic.md")

    report = index.sync(notes)

    assert report.unchanged == 3
    assert embedder.calls == []


def test_edits_and_deletions_are_reflected(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)
    _write(notes, "baking.md", "# Garden\n\nCompost the soil before planting seeds.\n")
    _bump_mtime(notes, "baking.md")
    (notes.vault.root_path / "logic.md").unlink()

    report = index.sync(notes)

    assert (report.updated, report.removed) == (1, 1)
    assert index.stats().notes == 2
    hits = index.search(_query(embedder, "boolean logic"), 10)
    assert P("logic.md") not in {hit.path for hit in hits}
    garden = index.search(_query(embedder, "compost and seeds"), 1)[0]
    assert garden.path == P("baking.md")
    assert "Compost" in garden.text


def test_index_note_and_remove_note_hooks(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    note = fs_vault.create_note(P("new.md"), "Telescope nights and planets.\n")

    index.index_note(note)
    assert index.search(_query(embedder, "astronomy"), 1)[0].path == P("new.md")

    index.remove_note(P("new.md"))
    assert index.stats().chunks == 0


def test_index_persists_across_restarts(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    first = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    first.sync(notes)
    before = first.search(_query(embedder, "yeast"), 3)
    first.close()

    reopened = SemanticIndex.for_vault(notes.vault.root_path, KeywordEmbedder())

    assert reopened.loaded_from_disk
    assert reopened.reset_reason is None
    assert reopened.search(_query(embedder, "yeast"), 3) == before
    assert reopened.sync(notes).unchanged == 3


def test_changing_the_model_resets_the_index(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    SemanticIndex.for_vault(notes.vault.root_path, embedder).sync(notes)

    other = SemanticIndex.for_vault(notes.vault.root_path, KeywordEmbedder("test/other"))

    assert not other.loaded_from_disk
    assert other.reset_reason and "settings changed" in other.reset_reason
    assert other.stats().chunks == 0
    assert other.sync(notes).added == 3


def test_corrupt_vector_file_resets_and_rebuilds(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    SemanticIndex.for_vault(notes.vault.root_path, embedder).sync(notes)
    (notes.vault.root_path / ".page" / "index" / FAISS_FILE).write_bytes(b"garbage")

    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    assert index.reset_reason and "could not be loaded" in index.reset_reason
    assert index.sync(notes).added == 3
    assert index.stats().chunks == 3


def test_vectors_out_of_step_with_metadata_reset(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)
    folder = notes.vault.root_path / ".page" / "index"
    stale_vectors = (folder / FAISS_FILE).read_bytes()
    _write(notes, "extra.md", "Sourdough flour.\n")
    index.sync(notes)
    index.close()
    # Simulate a crash after the metadata commit but before the vector file write.
    (folder / FAISS_FILE).write_bytes(stale_vectors)

    reopened = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    assert reopened.reset_reason and "out of step" in reopened.reset_reason


def test_query_with_wrong_dimension_is_incompatible(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)

    with pytest.raises(IndexIncompatibleError):
        index.search(np.ones((1, 4), dtype=np.float32), 3)


def test_unreadable_note_is_reported_and_not_indexed(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    (notes.vault.root_path / "binary.md").write_bytes(b"\xff\xfe not utf-8")
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    report = index.sync(notes)

    assert report.failed == ("binary.md",)
    assert index.stats().notes == 3


def test_empty_vault_gives_an_empty_index(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)

    assert index.sync(fs_vault).added == 0
    assert index.search(_query(embedder, "anything"), 5) == []


# --- Storage safety and recovery --------------------------------------------


def test_symlinked_index_folder_is_refused(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder, tmp_path: Path, symlinks: None
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, fs_vault.vault.root_path / ".page" / "index", target_is_directory=True)

    with pytest.raises(IndexStorageError):
        SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    assert list(outside.iterdir()) == []


def test_symlinked_database_file_is_refused(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder, tmp_path: Path, symlinks: None
) -> None:
    outside = tmp_path / "outside.sqlite"
    outside.write_bytes(b"")
    folder = fs_vault.vault.root_path / ".page" / "index"
    folder.mkdir()
    os.symlink(outside, folder / DB_FILE)

    with pytest.raises(IndexStorageError):
        SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    assert outside.read_bytes() == b""


@pytest.mark.parametrize("name", [DB_FILE, FAISS_FILE])
def test_index_entry_that_is_not_a_file_is_refused(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder, name: str
) -> None:
    SemanticIndex.for_vault(fs_vault.vault.root_path, embedder).close()
    entry = fs_vault.vault.root_path / ".page" / "index" / name
    entry.unlink()
    entry.mkdir()

    with pytest.raises(IndexStorageError):
        SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    assert entry.is_dir()


def test_corrupt_database_is_discarded_and_rebuilt(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    first = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    first.sync(notes)
    first.close()
    (notes.vault.root_path / ".page" / "index" / DB_FILE).write_bytes(b"not a database" * 100)

    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    assert index.reset_reason and "database was unreadable" in index.reset_reason
    assert not index.loaded_from_disk
    assert index.sync(notes).added == 3
    assert index.search(_query(embedder, "yeast"), 1)[0].path == P("baking.md")


# --- Chunk identity ------------------------------------------------------------


def _chunk_ids(index: SemanticIndex, embedder: KeywordEmbedder, path: str) -> dict[str, object]:
    hits = index.search(_query(embedder, "logic bread planet garden"), 100)
    return {hit.heading: hit.chunk_id for hit in hits if hit.path == P(path)}


def test_chunk_ids_survive_edits_to_other_chunks_and_restarts(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    _write(fs_vault, "mixed.md", "# A\n\nLogic gates.\n\n# B\n\nBread dough.\n\n# C\n\nPlanet orbit.\n")
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    index.sync(fs_vault)
    before = _chunk_ids(index, embedder, "mixed.md")
    embedder.calls.clear()

    _write(fs_vault, "mixed.md", "# A\n\nLogic gates.\n\n# B\n\nGarden soil.\n\n# C\n\nPlanet orbit.\n")
    _bump_mtime(fs_vault, "mixed.md")
    assert index.sync(fs_vault).updated == 1
    # Only the changed chunk was embedded.
    assert embedder.embedded_texts() == ["mixed\n\n# B\n\nGarden soil."]

    after = _chunk_ids(index, embedder, "mixed.md")
    assert after["A"] == before["A"]
    assert after["C"] == before["C"]
    assert after["B"] != before["B"]
    hit = next(h for h in index.search(_query(embedder, "planet"), 10) if h.heading == "C")
    content = (fs_vault.vault.root_path / "mixed.md").read_bytes()
    assert content[hit.start_byte : hit.end_byte].decode() == hit.text

    index.close()
    reopened = SemanticIndex.for_vault(fs_vault.vault.root_path, KeywordEmbedder())
    assert _chunk_ids(reopened, embedder, "mixed.md") == after


def test_moved_chunks_keep_ids_and_new_offsets(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    _write(fs_vault, "note.md", "# A\n\nLogic.\n\n# B\n\nBread.\n")
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    index.sync(fs_vault)
    before = _chunk_ids(index, embedder, "note.md")

    _write(fs_vault, "note.md", "# Intro\n\nPlanet.\n\n# B\n\nBread.\n\n# A\n\nLogic.\n")
    _bump_mtime(fs_vault, "note.md")
    index.sync(fs_vault)

    hits = {h.heading: h for h in index.search(_query(embedder, "logic bread planet"), 10)}
    assert hits["A"].chunk_id == before["A"] and hits["B"].chunk_id == before["B"]
    assert (hits["Intro"].ordinal, hits["B"].ordinal, hits["A"].ordinal) == (0, 1, 2)
    content = (fs_vault.vault.root_path / "note.md").read_bytes()
    for hit in hits.values():
        assert content[hit.start_byte : hit.end_byte].decode() == hit.text
