"""Stage 10 context optimizer: budgets, dedup, diversity, graph credit, excerpts."""
import hashlib
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import pytest

from page_core.context import ContextPackage, Utf8TokenEstimate, optimize_context
from page_core.domain import Chunk, Note
from page_core.graph import build_graph
from page_core.ranking import FEATURE_NAMES, Reranker, build_candidates
from test_ranking import DATA, KeywordEncoder

VAULT = UUID(int=1)
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def note(path: str, content: str) -> Note:
    return Note(uuid4(), VAULT, PurePosixPath(path), content, NOW, NOW)


def hit(source: Note, text: str, score: float, ordinal: int = 0):
    from page_core.semantic import SearchHit

    start = source.content.index(text)
    raw = source.content.encode()
    start_byte = len(source.content[:start].encode())
    end_byte = start_byte + len(text.encode())
    line = 1 + len(re.findall(r"\r\n|\r|\n", source.content[:start]))
    end_line = line + len(re.findall(r"\r\n|\r|\n", text.rstrip("\r\n")))
    assert raw[start_byte:end_byte].decode() == text
    return SearchHit(Chunk(uuid4(), source.id, ordinal, text, start_byte, end_byte, len(text.split())),
                     source.relative_path, hashlib.sha256(raw).hexdigest(), line, end_line, score)


def check(package: ContextPackage, notes: dict[UUID, Note]) -> None:
    """Invariants every package must satisfy."""
    result, usage = package.result, package.usage
    assert result.token_count <= result.token_budget == usage.budget
    assert usage.tokens == result.token_count
    assert usage.considered == (usage.selected + usage.dropped_redundant + usage.dropped_budget
                                + usage.dropped_relevance + usage.dropped_limit)
    assert usage.selected == len(package.blocks)
    for chunk in result.selected_chunks:
        raw = notes[chunk.note_id].content.encode()
        assert raw[chunk.start_byte:chunk.end_byte].decode() == chunk.text
    for block in package.blocks:
        assert f"[{block.number}] {block.relative_path} (" in result.context_text
        assert block.text in result.context_text


def garden():
    tomatoes = note("garden/tomatoes.md",
                    "# Tomatoes\n\nTomatoes need eight hours of sun every day.\n\n"
                    "Water tomatoes deeply at the base twice a week.\n\n"
                    "Stake tall tomato plants early. Pinch off suckers. Feed them compost in spring.\n")
    compost = note("garden/compost.md", "Turn the compost pile weekly to add air.\n\nSee [[garden/tomatoes]].\n")
    travel = note("travel/kyoto.md", "Carry yen because small restaurants take cash only.\n")
    notes = {n.id: n for n in (tomatoes, compost, travel)}
    hits = (hit(tomatoes, "Tomatoes need eight hours of sun every day.\n\n", 0.9),
            hit(tomatoes, "Water tomatoes deeply at the base twice a week.\n\n", 0.8, 1),
            hit(compost, "Turn the compost pile weekly to add air.\n\n", 0.6),
            hit(tomatoes, "Stake tall tomato plants early. Pinch off suckers. Feed them compost in spring.\n",
                0.5, 2),
            hit(travel, "Carry yen because small restaurants take cash only.\n", 0.1))
    return notes, hits, build_graph(VAULT, tuple(notes.values()))


def test_token_estimate() -> None:
    estimate = Utf8TokenEstimate()
    assert [estimate.count(t) for t in ("", "abc", "abcd", "日本")] == [0, 1, 2, 2]


def test_budget_is_never_exceeded() -> None:
    notes, hits, graph = garden()
    for budget in range(1, 300, 3):
        package = optimize_context("tomato sun water", hits, graph, budget=budget, min_relevance=0.0)
        check(package, notes)


def test_empty_candidates_give_an_empty_valid_package() -> None:
    _, _, graph = garden()
    package = optimize_context("anything", (), graph, budget=50)
    assert package.result.context_text == "" and package.result.token_count == 0
    assert package.blocks == () and package.usage.considered == 0


def test_low_relevance_and_passage_limit() -> None:
    notes, hits, graph = garden()
    package = optimize_context("tomato sun", hits, graph, budget=1000)
    assert package.usage.dropped_relevance == 1  # the travel note
    assert all(block.relative_path != PurePosixPath("travel/kyoto.md") for block in package.blocks)
    limited = optimize_context("tomato sun", hits, graph, budget=1000, max_passages=1)
    assert limited.usage.selected == 1 and limited.usage.dropped_limit >= 1
    check(limited, notes)


def test_exact_and_near_duplicates_are_dropped() -> None:
    a = note("a.md", "Water tomatoes deeply at the base twice a week.\n")
    b = note("b.md", "Water tomatoes deeply at the base twice a week.\n")
    c = note("c.md", "Water the tomatoes deeply at the base twice a week.\n")
    notes = {n.id: n for n in (a, b, c)}
    hits = (hit(a, a.content, 0.9), hit(b, b.content, 0.9), hit(c, c.content, 0.88))
    package = optimize_context("water tomatoes", hits, build_graph(VAULT, (a, b, c)),
                               budget=1000, min_relevance=0.0)
    assert package.usage.selected == 1 and package.usage.dropped_redundant == 2
    check(package, notes)


def test_complementary_passages_beat_repetitive_ones() -> None:
    a = note("a.md", "Tomatoes need full sun all day long.\n")
    b = note("b.md", "Tomatoes need full sun for most of the day.\n")
    c = note("c.md", "Water deeply twice a week.\n")
    hits = (hit(a, a.content, 0.9), hit(b, b.content, 0.88), hit(c, c.content, 0.8))
    package = optimize_context("tomatoes sun water", hits, build_graph(VAULT, (a, b, c)),
                               budget=1000, max_passages=2, min_relevance=0.0, redundancy_threshold=1.0)
    assert [block.relative_path.name for block in package.blocks] == ["a.md", "c.md"]


def test_graph_credit_prefers_notes_linked_to_the_selection() -> None:
    top = note("top.md", "Compost feeds the garden beds.\n\nSee [[linked]].\n")
    other = note("other.md", "Mulch keeps soil moist.\n")
    linked = note("linked.md", "Mulch keeps soil cool.\n")
    graph = build_graph(VAULT, (top, other, linked))
    hits = (hit(top, "Compost feeds the garden beds.\n\n", 0.9), hit(other, other.content, 0.5),
            hit(linked, linked.content, 0.5))
    with_graph = optimize_context("compost mulch", hits, graph, budget=1000, max_passages=2,
                                  min_relevance=0.0)
    without = optimize_context("compost mulch", hits, graph, budget=1000, max_passages=2,
                               min_relevance=0.0, graph_weight=0.0)
    assert with_graph.blocks[1].relative_path.name == "linked.md"
    assert without.blocks[1].relative_path.name == "other.md"


def test_oversized_passage_becomes_an_exact_excerpt() -> None:
    notes, hits, graph = garden()
    long_hit = hits[3]
    package = optimize_context("compost feed", (long_hit,), graph, budget=25, min_relevance=0.0)
    (block,) = package.blocks
    assert block.compressed and package.usage.compressed == 1
    assert block.text == "Feed them compost in spring."
    assert block.start_line == block.end_line == long_hit.start_line
    assert "excerpt" in package.result.context_text
    check(package, notes)


def test_passages_that_cannot_fit_are_dropped() -> None:
    notes, hits, graph = garden()
    package = optimize_context("tomato", hits, graph, budget=3, min_relevance=0.0)
    assert package.blocks == () and package.usage.dropped_budget == package.usage.considered
    check(package, notes)


def test_blocks_name_sources_and_shown_lines() -> None:
    notes, hits, graph = garden()
    package = optimize_context("tomato sun", hits[:1], graph, budget=1000)
    (block,) = package.blocks
    assert (block.start_line, block.end_line) == (3, 3)  # trailing blank line not shown
    assert package.result.context_text.startswith("[1] garden/tomatoes.md (line 3)\nTomatoes need")


def test_reranker_scores_order_the_candidates() -> None:
    notes, hits, graph = garden()
    width = len(FEATURE_NAMES)
    cosine = FEATURE_NAMES.index("cosine")
    favor_low_cosine = Reranker(tuple(0.0 for _ in range(width)), tuple(1.0 for _ in range(width)),
                                (tuple(-1.0 if i == cosine else 0.0 for i in range(width)),),
                                (1.0,), (1.0,), 0.0)
    package = optimize_context("tomato", hits, graph, budget=1000, reranker=favor_low_cosine,
                               max_passages=1, min_relevance=0.0)
    assert package.blocks[0].relative_path.name == "kyoto.md"


def test_results_are_deterministic() -> None:
    _, hits, graph = garden()
    first = optimize_context("tomato sun water", hits, graph, budget=60)
    assert optimize_context("tomato sun water", hits, graph, budget=60) == first


class WordCounter:
    name = "words"

    def count(self, text: str) -> int:
        return len(text.split())


def test_custom_token_counter_is_used() -> None:
    notes, hits, graph = garden()
    package = optimize_context("tomato", hits, graph, budget=20, counter=WordCounter(), min_relevance=0.0)
    assert package.usage.counter == "words"
    assert package.result.token_count == len(package.result.context_text.split()) <= 20
    check(package, notes)


@pytest.mark.parametrize("kwargs, error", [
    ({"budget": 0}, ValueError), ({"budget": True}, TypeError), ({"budget": 1.5}, TypeError),
    ({"max_passages": 0}, ValueError), ({"min_relevance": 1.5}, ValueError),
    ({"diversity": -0.1}, ValueError), ({"graph_weight": float("nan")}, ValueError),
    ({"reranker": "model"}, TypeError), ({"counter": object()}, TypeError),
])
def test_invalid_arguments_are_rejected(kwargs, error) -> None:
    _, hits, graph = garden()
    arguments = {"budget": 100, **kwargs}
    with pytest.raises(error):
        optimize_context("tomato", hits, graph, **arguments)


def test_invalid_inputs_are_rejected() -> None:
    _, hits, graph = garden()
    with pytest.raises(ValueError, match="baseline order"):
        optimize_context("tomato", tuple(reversed(hits)), graph, budget=100)
    with pytest.raises(TypeError):
        optimize_context(None, hits, graph, budget=100)  # type: ignore[arg-type]

    class Broken:
        name = "broken"

        def count(self, text: str) -> int:
            return -1

    with pytest.raises(ValueError, match="nonnegative"):
        optimize_context("tomato", hits, graph, budget=100, counter=Broken())


def test_fixture_vault_packages_fit_and_save_tokens() -> None:
    candidates = build_candidates(DATA, KeywordEncoder(), limit=10)
    for query, hits, graph in candidates:
        package = optimize_context(query.query, hits, graph, budget=150)
        assert package.result.token_count <= 150
        assert package.result.token_count <= package.usage.candidate_tokens


def test_importing_context_does_not_import_torch() -> None:
    script = "import sys, page_core.context\nprint('torch' in sys.modules)\n"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"
