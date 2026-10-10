from pathlib import PurePosixPath

import pytest

from embedding_fakes import KeywordEmbedder
from page_core.domain import Note
from page_core.embeddings import SemanticIndex
from page_core.retrieval import QueryValidationError, SemanticSearchService
from page_core.vault import FileSystemVault, VaultError

P = PurePosixPath


def _write(vault: FileSystemVault, path: str, content: str) -> None:
    target = vault.vault.root_path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content.encode("utf-8"))


def _service(vault: FileSystemVault, embedder: KeywordEmbedder) -> SemanticSearchService:
    index = SemanticIndex.for_vault(vault.vault.root_path, embedder, max_chunk_chars=80)
    index.sync(vault)

    def read(path: PurePosixPath) -> Note | None:
        try:
            return vault.read_note(path)
        except VaultError:
            return None

    return SemanticSearchService(index, embedder, read)


@pytest.fixture
def embedder() -> KeywordEmbedder:
    return KeywordEmbedder()


@pytest.fixture
def vault(fs_vault: FileSystemVault) -> FileSystemVault:
    # logic.md has several matching chunks; the others have one or none.
    _write(
        fs_vault,
        "logic.md",
        "# Karnaugh maps\n\nGroup ones to minimize boolean gates.\n\n"
        "# Gates\n\nEvery digital circuit is built from logic gates.\n\n"
        "# Unrelated\n\nBake bread on Sunday.\n",
    )
    _write(fs_vault, "notes/circuits.md", "A boolean circuit diagram.\n")
    _write(fs_vault, "baking.md", "Knead the dough, then let yeast rise.\n")
    _write(fs_vault, "space.md", "Planets orbit a star.\n")
    return fs_vault


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_blank_queries_are_rejected(vault: FileSystemVault, embedder: KeywordEmbedder, query: str) -> None:
    with pytest.raises(QueryValidationError, match="blank"):
        _service(vault, embedder).search(query)


@pytest.mark.parametrize("limit", [0, 51, True, "5"])
def test_invalid_limits_are_rejected(vault: FileSystemVault, embedder: KeywordEmbedder, limit: object) -> None:
    with pytest.raises(QueryValidationError):
        _service(vault, embedder).search("logic", limit)  # type: ignore[arg-type]


def test_query_is_embedded_once_with_the_index_model(
    vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    service = _service(vault, embedder)
    embedder.calls.clear()

    result = service.search("  how do I simplify a digital logic circuit?  ")

    assert embedder.calls == [["how do I simplify a digital logic circuit?"]]
    assert result.query == "how do I simplify a digital logic circuit?"


def test_mismatched_query_embedder_is_refused(vault: FileSystemVault, embedder: KeywordEmbedder) -> None:
    index = SemanticIndex.for_vault(vault.vault.root_path, embedder)
    with pytest.raises(ValueError):
        SemanticSearchService(index, KeywordEmbedder("test/other"), lambda path: None)


def test_matches_paraphrase_and_groups_chunks_per_note(
    vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    result = _service(vault, embedder).search("how do I simplify a digital logic circuit?", 10)

    paths = [match.path for match in result.matches]
    assert paths[:2] == [P("logic.md"), P("notes/circuits.md")]
    assert len(paths) == len(set(paths)) == 4
    logic = result.matches[0]
    assert logic.matched_chunks == 3
    assert logic.title == "logic"
    assert logic.note_id == vault.read_note(P("logic.md")).id
    scores = [match.score for match in result.matches]
    assert scores == sorted(scores, reverse=True)
    assert -1.0 <= scores[-1] <= scores[0] <= 1.0 + 1e-6


def test_result_metadata_points_at_real_note_text(
    vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    matches = _service(vault, embedder).search("boolean gates", 10).matches
    match = next(m for m in matches if m.path == P("logic.md"))

    data = vault.read_note(match.path).content.encode("utf-8")
    chunk = data[match.start_byte : match.end_byte].decode("utf-8")
    assert match.excerpt == chunk
    assert match.heading == "Karnaugh maps"
    assert match.chunk_ordinal == 0


def test_limit_caps_distinct_notes(vault: FileSystemVault, embedder: KeywordEmbedder) -> None:
    result = _service(vault, embedder).search("logic", 2)

    assert len(result.matches) == 2


def test_ties_are_ordered_by_path(fs_vault: FileSystemVault, embedder: KeywordEmbedder) -> None:
    for name in ("b.md", "a.md", "c.md"):
        _write(fs_vault, name, "Yeast.\n")
    _write(fs_vault, "x.md", "Yeast.\n")

    result = _service(fs_vault, embedder).search("yeast", 4)

    # Same text but titles differ only in non-vocabulary words, so scores tie.
    assert [str(m.path) for m in result.matches] == ["a.md", "b.md", "c.md", "x.md"]


def test_search_widens_until_enough_distinct_notes(
    fs_vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    _write(fs_vault, "big.md", "\n\n".join(f"# Part {i}\n\nboolean logic" for i in range(60)))
    _write(fs_vault, "small.md", "boolean\n")

    result = _service(fs_vault, embedder).search("boolean logic", 2)

    assert [str(m.path) for m in result.matches] == ["big.md", "small.md"]
    assert result.candidates_considered > 20


def test_empty_index_returns_no_matches(fs_vault: FileSystemVault, embedder: KeywordEmbedder) -> None:
    result = _service(fs_vault, embedder).search("anything at all")

    assert result.matches == ()
    assert result.stale_paths == ()


def test_deleted_and_edited_notes_are_filtered_before_sync(
    vault: FileSystemVault, embedder: KeywordEmbedder
) -> None:
    service = _service(vault, embedder)
    (vault.vault.root_path / "notes" / "circuits.md").unlink()
    _write(vault, "logic.md", "Completely rewritten: boolean logic.\n")

    result = service.search("boolean circuit", 10)

    paths = {match.path for match in result.matches}
    assert P("notes/circuits.md") not in paths
    assert P("logic.md") not in paths  # its indexed bytes no longer match the file
    assert set(result.stale_paths) == {P("logic.md"), P("notes/circuits.md")}
