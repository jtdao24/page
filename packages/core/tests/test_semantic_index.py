import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath

import faiss
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


# --- Note identity across renames ----------------------------------------------


def test_rename_keeps_note_and_chunk_ids_across_restart(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)
    note_id = index.note_id_for(P("logic.md"))
    chunk_id = index.search(_query(embedder, "boolean"), 1)[0].chunk_id
    root = notes.vault.root_path
    (root / "archive").mkdir()
    os.replace(root / "logic.md", root / "archive" / "Digital Logic.md")

    report = index.sync(notes)

    assert (report.added, report.moved, report.removed) == (0, 1, 0)
    assert index.note_id_for(P("logic.md")) is None
    assert index.note_id_for(P("archive/Digital Logic.md")) == note_id
    hit = index.search(_query(embedder, "boolean"), 1)[0]
    assert (hit.path, hit.note_id, hit.chunk_id) == (
        P("archive/Digital Logic.md"),
        note_id,
        chunk_id,
    )
    index.close()

    reopened = SemanticIndex.for_vault(root, KeywordEmbedder())
    assert reopened.note_id_for(P("archive/Digital Logic.md")) == note_id
    assert reopened.search(_query(embedder, "boolean"), 1)[0].chunk_id == chunk_id


def test_rename_re_embeds_with_the_new_title(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    _write(fs_vault, "untitled.md", "Some text.\n")
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    index.sync(fs_vault)
    root = fs_vault.vault.root_path
    os.replace(root / "untitled.md", root / "Telescope.md")
    embedder.calls.clear()

    index.sync(fs_vault)

    assert embedder.embedded_texts() == ["Telescope\n\nSome text."]
    assert index.search(_query(embedder, "astronomy"), 1)[0].path == P("Telescope.md")


def test_swapped_paths_keep_their_identities(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    _write(fs_vault, "a.md", "Logic gates.\n")
    _write(fs_vault, "b.md", "Bread dough.\n")
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    index.sync(fs_vault)
    logic_id = index.note_id_for(P("a.md"))
    bread_id = index.note_id_for(P("b.md"))
    root = fs_vault.vault.root_path
    os.replace(root / "a.md", root / "tmp.md")
    os.replace(root / "b.md", root / "a.md")
    os.replace(root / "tmp.md", root / "b.md")

    report = index.sync(fs_vault)

    assert report.moved == 2
    assert index.note_id_for(P("b.md")) == logic_id
    assert index.note_id_for(P("a.md")) == bread_id
    assert index.search(_query(embedder, "logic"), 1)[0].path == P("b.md")


def test_edit_keeps_note_id(notes: FileSystemVault, embedder: KeywordEmbedder) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)
    note_id = index.note_id_for(P("baking.md"))
    _write(notes, "baking.md", "# Bread\n\nSourdough flour.\n")
    _bump_mtime(notes, "baking.md")

    assert index.sync(notes).updated == 1
    assert index.note_id_for(P("baking.md")) == note_id


def test_deleted_then_different_note_gets_a_new_id(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)
    old_id = index.note_id_for(P("baking.md"))
    (notes.vault.root_path / "baking.md").unlink()
    _write(notes, "other.md", "Compost and seeds.\n")

    report = index.sync(notes)

    assert (report.added, report.moved, report.removed) == (1, 0, 1)
    assert index.note_id_for(P("other.md")) not in {None, old_id}


def test_older_index_format_is_rebuilt(notes: FileSystemVault, embedder: KeywordEmbedder) -> None:
    SemanticIndex.for_vault(notes.vault.root_path, embedder).close()
    database = notes.vault.root_path / ".page" / "index" / DB_FILE
    conn = sqlite3.connect(database)
    conn.execute("UPDATE meta SET value = '2' WHERE key = 'format'")
    conn.commit()
    conn.close()

    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    assert index.reset_reason and "settings changed" in index.reset_reason
    assert index.sync(notes).added == 3


# --- Hard links ---------------------------------------------------------------


@pytest.fixture
def hardlinks(tmp_path: Path) -> None:
    source = tmp_path / "link-probe"
    source.write_bytes(b"")
    try:
        os.link(source, tmp_path / "link-probe-2")
    except (OSError, NotImplementedError):
        pytest.skip("hard links are not supported here")


def _external_database(path: Path) -> bytes:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE precious (value TEXT)")
    conn.execute("INSERT INTO precious VALUES ('keep me')")
    conn.commit()
    conn.close()
    return path.read_bytes()


@pytest.mark.parametrize("name", [DB_FILE, f"{DB_FILE}-journal", f"{DB_FILE}-wal"])
def test_hard_linked_database_files_are_refused(
    fs_vault: FileSystemVault,
    embedder: KeywordEmbedder,
    tmp_path: Path,
    hardlinks: None,
    name: str,
) -> None:
    external = tmp_path / "external.sqlite"
    before = _external_database(external)
    folder = fs_vault.vault.root_path / ".page" / "index"
    folder.mkdir()
    os.link(external, folder / name)

    with pytest.raises(IndexStorageError, match="hard links"):
        SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    assert external.read_bytes() == before


def test_hard_linked_vector_file_is_refused(
    notes: FileSystemVault, embedder: KeywordEmbedder, tmp_path: Path, hardlinks: None
) -> None:
    SemanticIndex.for_vault(notes.vault.root_path, embedder).sync(notes)
    vectors = notes.vault.root_path / ".page" / "index" / FAISS_FILE
    os.link(vectors, tmp_path / "outside.faiss")
    before = (tmp_path / "outside.faiss").read_bytes()

    with pytest.raises(IndexStorageError, match="hard links"):
        SemanticIndex.for_vault(notes.vault.root_path, embedder)
    assert (tmp_path / "outside.faiss").read_bytes() == before


# --- Persisted vector validation ------------------------------------------------


def _replace_vectors(
    notes: FileSystemVault, build: Callable[[int, np.ndarray, np.ndarray], faiss.Index]
) -> None:
    folder = notes.vault.root_path / ".page" / "index"
    data = np.frombuffer((folder / FAISS_FILE).read_bytes(), dtype=np.uint8)
    original = faiss.deserialize_index(data)
    ids = faiss.vector_to_array(original.id_map)
    vectors = original.index.reconstruct_n(0, original.ntotal)
    replacement = build(original.d, vectors, ids)
    (folder / FAISS_FILE).write_bytes(faiss.serialize_index(replacement).tobytes())


def test_l2_vector_file_is_rebuilt_as_inner_product(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    SemanticIndex.for_vault(notes.vault.root_path, embedder).sync(notes)

    def l2(d: int, vectors: np.ndarray, ids: np.ndarray) -> faiss.Index:
        index = faiss.IndexIDMap2(faiss.IndexFlatL2(d))
        index.add_with_ids(vectors, ids)
        return index

    _replace_vectors(notes, l2)
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    assert index.reset_reason and "inner-product" in index.reset_reason
    index.sync(notes)
    hits = index.search(_query(embedder, "yeast dough"), 3)
    assert hits[0].path == P("baking.md")
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


def test_vector_file_with_duplicate_ids_is_rebuilt(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    SemanticIndex.for_vault(notes.vault.root_path, embedder).sync(notes)

    def duplicated(d: int, vectors: np.ndarray, ids: np.ndarray) -> faiss.Index:
        index = faiss.IndexIDMap2(faiss.IndexFlatIP(d))
        index.add_with_ids(vectors, ids)
        index.add_with_ids(vectors[:1], ids[:1])
        return index

    _replace_vectors(notes, duplicated)
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    assert index.reset_reason and "duplicate" in index.reset_reason


def test_vector_file_without_id_map_is_rebuilt(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    SemanticIndex.for_vault(notes.vault.root_path, embedder).sync(notes)

    def flat(d: int, vectors: np.ndarray, ids: np.ndarray) -> faiss.Index:
        index = faiss.IndexFlatIP(d)
        index.add(vectors)
        return index

    _replace_vectors(notes, flat)
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)

    assert index.reset_reason and "ID-mapped" in index.reset_reason


def test_overwritten_note_hands_over_its_identity_without_leaks(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    # a.md takes over b.md's content and b.md gets new content: b's identity
    # follows its content to a.md, a's old note is removed, b.md is a new note.
    _write(fs_vault, "a.md", "Logic gates.\n")
    _write(fs_vault, "b.md", "Bread dough.\n")
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    index.sync(fs_vault)
    logic_id = index.note_id_for(P("a.md"))
    bread_id = index.note_id_for(P("b.md"))
    _write(fs_vault, "a.md", "Bread dough.\n")
    _write(fs_vault, "b.md", "Planet orbits.\n")
    _bump_mtime(fs_vault, "a.md")
    _bump_mtime(fs_vault, "b.md")

    report = index.sync(fs_vault)

    assert (report.added, report.updated, report.moved, report.removed) == (1, 0, 1, 1)
    assert index.note_id_for(P("a.md")) == bread_id
    assert index.note_id_for(P("b.md")) not in {None, logic_id, bread_id}
    assert index.stats().notes == 2
    assert index.stats().chunks == 2
    index.close()
    assert SemanticIndex.for_vault(fs_vault.vault.root_path, embedder).loaded_from_disk


def test_copied_note_gets_its_own_identity(
    notes: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    index = SemanticIndex.for_vault(notes.vault.root_path, embedder)
    index.sync(notes)
    original = index.note_id_for(P("logic.md"))
    root = notes.vault.root_path
    (root / "copy.md").write_bytes((root / "logic.md").read_bytes())

    report = index.sync(notes)

    assert (report.added, report.moved) == (1, 0)
    assert index.note_id_for(P("logic.md")) == original
    assert index.note_id_for(P("copy.md")) not in {None, original}


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows feature")
def test_junctioned_index_folder_is_refused(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder, tmp_path: Path
) -> None:
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(fs_vault.vault.root_path / ".page" / "index"))

    with pytest.raises(IndexStorageError):
        SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    assert list(outside.iterdir()) == []


def _set_mtime(vault: FileSystemVault, path: str, mtime_ns: int) -> None:
    target = vault.vault.root_path / path
    os.utime(target, ns=(os.stat(target).st_atime_ns, mtime_ns))


def test_swap_is_detected_even_with_identical_sizes_and_times(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    # Coarse file clocks can give both files the same time; the inode still differs.
    an_hour_ago = time.time_ns() - 3_600_000_000_000
    _write(fs_vault, "a.md", "Logic gates.\n")
    _write(fs_vault, "b.md", "Bread dough.\n")
    _set_mtime(fs_vault, "a.md", an_hour_ago)
    _set_mtime(fs_vault, "b.md", an_hour_ago)
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    index.sync(fs_vault)
    logic_id = index.note_id_for(P("a.md"))
    root = fs_vault.vault.root_path
    os.replace(root / "a.md", root / "tmp.md")
    os.replace(root / "b.md", root / "a.md")
    os.replace(root / "tmp.md", root / "b.md")

    assert index.sync(fs_vault).moved == 2
    assert index.note_id_for(P("b.md")) == logic_id


def test_same_size_edit_in_the_same_clock_tick_is_detected(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    _write(fs_vault, "note.md", "Logic gates.\n")
    index = SemanticIndex.for_vault(fs_vault.vault.root_path, embedder)
    index.sync(fs_vault)
    target = fs_vault.vault.root_path / "note.md"
    before = os.stat(target).st_mtime_ns
    with open(target, "r+b") as stream:  # in place: same file, same size
        stream.write(b"Bread dough.\n")
    _set_mtime(fs_vault, "note.md", before)

    assert index.sync(fs_vault).updated == 1
    assert index.search(_query(embedder, "yeast"), 1)[0].text == "Bread dough."
