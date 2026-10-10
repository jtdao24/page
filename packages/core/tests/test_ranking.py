"""Reranker: features, deterministic training, safe checkpoints, metrics."""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import pytest

from page_core.domain import Chunk, Note
from page_core.graph import build_graph
from page_core.ranking import (
    FEATURE_NAMES, Reranker, TrainingGroup, build_candidates, evaluate, extract_features,
    load_queries, ranking_metrics, train_reranker, training_groups,
)
from page_core.semantic import SearchHit

DATA = Path(__file__).resolve().parents[3] / "training" / "reranker"
VAULT = UUID(int=1)
NOW = datetime(2026, 1, 1, tzinfo=UTC)
FIELD = {name: index for index, name in enumerate(FEATURE_NAMES)}


def make_note(path: str, content: str) -> Note:
    return Note(uuid4(), VAULT, PurePosixPath(path), content, NOW, NOW)


def make_hit(note: Note, text: str, score: float, ordinal: int = 0) -> SearchHit:
    start = note.content.encode().index(text.encode())
    chunk = Chunk(uuid4(), note.id, ordinal, text, start, start + len(text.encode()), len(text.split()))
    return SearchHit(chunk, note.relative_path, hashlib.sha256(note.content.encode()).hexdigest(), 1, 1, score)


def graph_fixture():
    a = make_note("a.md", "# Fruit apples\n\nSee [[b]].")
    b = make_note("b.md", "Pears and plums.")
    c = make_note("garden/fruit.md", "Links to [[b]].")
    hits = (make_hit(a, "# Fruit apples\n\n", 0.9), make_hit(b, "Pears and plums.", 0.8),
            make_hit(c, "Links to [[b]].", 0.5, ordinal=1))
    return hits, build_graph(VAULT, (a, b, c))


def random_reranker(seed: int = 3, hidden: int = 4) -> Reranker:
    import random

    rng = random.Random(seed)
    width = len(FEATURE_NAMES)
    return Reranker(
        tuple(rng.uniform(-1, 1) for _ in range(width)), tuple(rng.uniform(0.5, 2) for _ in range(width)),
        tuple(tuple(rng.uniform(-1, 1) for _ in range(width)) for _ in range(hidden)),
        tuple(rng.uniform(-1, 1) for _ in range(hidden)), tuple(rng.uniform(-1, 1) for _ in range(hidden)),
        rng.uniform(-1, 1))


# --- Features -------------------------------------------------------------------


def test_feature_values_for_crafted_hits_and_graph() -> None:
    hits, graph = graph_fixture()
    rows = extract_features("fruit apples", hits, graph)

    assert len(rows) == 3 and all(len(row) == len(FEATURE_NAMES) for row in rows)
    a, b, c = rows
    assert [row[FIELD["cosine"]] for row in rows] == [0.9, 0.8, 0.5]
    assert [row[FIELD["baseline_reciprocal_rank"]] for row in rows] == [1.0, 0.5, 1 / 3]
    assert c[FIELD["gap_to_top"]] == pytest.approx(-0.4)
    assert a[FIELD["query_terms_in_passage"]] == 1.0 and b[FIELD["query_terms_in_passage"]] == 0.0
    assert c[FIELD["query_terms_in_path"]] == 0.5  # "fruit" in garden/fruit
    assert (a[FIELD["is_heading"]], b[FIELD["is_heading"]]) == (1.0, 0.0)
    assert (a[FIELD["is_first_passage"]], c[FIELD["is_first_passage"]]) == (1.0, 0.0)
    assert b[FIELD["backlinks"]] == pytest.approx(math.log1p(2) / (1 + math.log1p(2)))
    assert a[FIELD["backlinks"]] == 0.0
    assert (b[FIELD["links_top_note"]], c[FIELD["links_top_note"]]) == (1.0, 0.0)
    assert a[FIELD["links_other_candidates"]] == 0.5 and b[FIELD["links_other_candidates"]] == 1.0
    assert all(math.isfinite(v) for row in rows for v in row)


def test_features_validate_inputs() -> None:
    hits, graph = graph_fixture()
    assert extract_features("anything", (), graph) == []
    with pytest.raises(ValueError, match="baseline order"):
        extract_features("fruit", tuple(reversed(hits)), graph)
    with pytest.raises(TypeError):
        extract_features(None, hits, graph)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        extract_features("fruit", hits, None)  # type: ignore[arg-type]


# --- Training and inference -----------------------------------------------------


def planted_groups(count: int, seed: int) -> list[TrainingGroup]:
    """The relevant candidate is never the baseline's first, but has full term coverage."""
    import random

    rng = random.Random(seed)
    groups = []
    for _ in range(count):
        relevant = rng.randrange(1, 5)
        rows, flags = [], []
        for rank in range(5):
            row = [rng.uniform(-0.1, 0.1) for _ in FEATURE_NAMES]
            row[FIELD["cosine"]] = 0.9 - 0.1 * rank
            row[FIELD["baseline_reciprocal_rank"]] = 1 / (rank + 1)
            row[FIELD["query_terms_in_passage"]] = 1.0 if rank == relevant else rng.uniform(0, 0.3)
            rows.append(tuple(row))
            flags.append(rank == relevant)
        groups.append(TrainingGroup(tuple(rows), tuple(flags)))
    return groups


def test_training_is_deterministic_and_learns_a_planted_signal() -> None:
    first = train_reranker(planted_groups(30, seed=1), epochs=150)
    second = train_reranker(planted_groups(30, seed=1), epochs=150)
    assert first == second

    for group in planted_groups(20, seed=99):
        scores = [first.score(row) for row in group.features]
        assert group.relevant[scores.index(max(scores))]


def test_training_rejects_unusable_data() -> None:
    row = tuple(0.0 for _ in FEATURE_NAMES)
    with pytest.raises(ValueError, match="relevant candidate"):
        train_reranker([TrainingGroup((row, row), (False, False)), TrainingGroup((row,), (True,))])
    with pytest.raises(ValueError):
        TrainingGroup((row,), (True, False))


def test_python_inference_matches_the_torch_forward_pass() -> None:
    import torch

    reranker = random_reranker()
    rows = [tuple(float(i * j % 7) / 7 for j in range(len(FEATURE_NAMES))) for i in range(6)]
    x = (torch.tensor(rows, dtype=torch.float64) - torch.tensor(reranker.mean, dtype=torch.float64)) \
        / torch.tensor(reranker.std, dtype=torch.float64)
    hidden = torch.relu(x @ torch.tensor(reranker.hidden_weight, dtype=torch.float64).T
                        + torch.tensor(reranker.hidden_bias, dtype=torch.float64))
    expected = hidden @ torch.tensor(reranker.output_weight, dtype=torch.float64) + reranker.output_bias
    assert [reranker.score(row) for row in rows] == pytest.approx(expected.tolist(), abs=1e-12)


def test_rerank_orders_by_score_and_keeps_baseline_order_on_ties() -> None:
    hits, graph = graph_fixture()
    flat = replace(random_reranker(), output_weight=tuple(0.0 for _ in range(4)), output_bias=0.0)
    assert [item.baseline_rank for item in flat.rerank("fruit", hits, graph)] == [1, 2, 3]

    # One hidden unit computing 1 - cosine: prefers the lowest baseline score.
    width = len(FEATURE_NAMES)
    favor_last = Reranker(tuple(0.0 for _ in range(width)), tuple(1.0 for _ in range(width)),
                          (tuple(-1.0 if i == FIELD["cosine"] else 0.0 for i in range(width)),),
                          (1.0,), (1.0,), 0.0)
    ranked = favor_last.rerank("fruit", hits, graph)
    assert [item.baseline_rank for item in ranked] == [3, 2, 1]
    assert ranked[0].hit is hits[2]
    assert favor_last.rerank("fruit", (), graph) == ()


# --- Checkpoints ----------------------------------------------------------------


def test_checkpoint_round_trip(tmp_path: Path) -> None:
    reranker = replace(random_reranker(), training=(("seed", 0),))
    path = tmp_path / "model.json"
    reranker.save(path)
    loaded = Reranker.load(path)
    assert loaded == reranker
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize("tamper", [
    lambda d: d.update(format="pickle"),
    lambda d: d.update(feature_version="rank-features-v0"),
    lambda d: d.update(feature_names=list(reversed(d["feature_names"]))),
    lambda d: d["mean"].pop(),
    lambda d: d["hidden_weight"][0].append(1.0),
    lambda d: d.update(output_bias=float("nan")),
    lambda d: d["std"].__setitem__(0, 0.0),
    lambda d: d["hidden_bias"].__setitem__(0, True),
    lambda d: d.update(training=["not", "an", "object"]),
])
def test_tampered_checkpoints_are_rejected(tmp_path: Path, tamper) -> None:
    data = random_reranker().to_json()
    tamper(data)
    path = tmp_path / "model.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        Reranker.load(path)


def test_invalid_json_checkpoint_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "model.json").write_text("{not json")
    with pytest.raises(ValueError):
        Reranker.load(tmp_path / "model.json")


# --- Metrics and data -----------------------------------------------------------


def test_ranking_metrics() -> None:
    metrics = ranking_metrics([([True, False], 1), ([False, False, True], 1), ([False] * 5, 1),
                               ([True, True, False], 2)])
    assert metrics.queries == 4
    assert metrics.recall_at_1 == pytest.approx((1 + 0 + 0 + 0.5) / 4)
    assert metrics.recall_at_3 == pytest.approx((1 + 1 + 0 + 1) / 4)
    assert metrics.mrr == pytest.approx((1 + 1 / 3 + 0 + 1) / 4)
    with pytest.raises(ValueError):
        ranking_metrics([])


@pytest.mark.parametrize("line", [
    "not json",
    '{"id": "q", "split": "train", "query": "x"}',
    '{"id": "q", "split": "dev", "query": "x", "relevant": [{"path": "a.md", "contains": "x"}]}',
    '{"id": "q", "split": "train", "query": " ", "relevant": [{"path": "a.md", "contains": "x"}]}',
    '{"id": "q", "split": "train", "query": "x", "relevant": []}',
    '{"id": "q", "split": "train", "query": "x", "relevant": [{"path": "../a.md", "contains": "x"}]}',
    '{"id": "q", "split": "train", "query": "x", "relevant": [{"path": "a.md", "contains": ""}]}',
])
def test_query_files_are_strictly_validated(tmp_path: Path, line: str) -> None:
    (tmp_path / "queries.jsonl").write_text(line + "\n")
    with pytest.raises((ValueError, TypeError)):
        load_queries(tmp_path / "queries.jsonl")


def test_duplicate_query_ids_are_rejected(tmp_path: Path) -> None:
    line = '{"id": "q", "split": "train", "query": "x", "relevant": [{"path": "a.md", "contains": "x"}]}'
    (tmp_path / "queries.jsonl").write_text(f"{line}\n{line}\n")
    with pytest.raises(ValueError, match="unique"):
        load_queries(tmp_path / "queries.jsonl")


def test_fixture_dataset_is_consistent() -> None:
    queries = load_queries(DATA / "queries.jsonl")
    assert {q.split for q in queries} == {"train", "test"}
    for query in queries:
        for path, snippet in query.relevant:
            assert snippet in (DATA / "vault" / path).read_text(encoding="utf-8"), (query.id, path)


class KeywordEncoder:
    """Offline stand-in for MiniLM: one axis per fixture topic, plus a bias."""

    fingerprint = "test-keyword-encoder-v1"
    dimension = 7
    TOPICS = ("tomato|compost|seed|garden|soil|bean", "bread|dough|flour|pasta|bake|starter",
              "transaction|index|database|sql|query|row", "telescope|planet|jupiter|saturn|mars|star",
              "test|mock|fixture|assert|python", "kyoto|temple|yen|bus|shrine|maple")

    def offsets(self, text: str) -> list[tuple[int, int]]:
        return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]

    def encode(self, texts):
        return [[float(len(re.findall(topic, text.lower()))) for topic in self.TOPICS] + [0.2]
                for text in texts]


def test_pipeline_on_the_fixture_vault_with_an_offline_encoder() -> None:
    before = sorted(p.relative_to(DATA) for p in DATA.rglob("*"))
    candidates = build_candidates(DATA, KeywordEncoder(), limit=5)

    assert len(candidates) == len(load_queries(DATA / "queries.jsonl"))
    assert all(1 <= len(hits) <= 5 for _, hits, _ in candidates)
    groups = training_groups(candidates)
    assert len(groups) == sum(q.split == "train" for q, _, _ in candidates)
    report = evaluate(train_reranker(groups, epochs=60), candidates)
    assert report["split"] == "test"
    assert report["baseline"]["queries"] == report["reranker"]["queries"] == len(report["per_query"])
    assert sorted(p.relative_to(DATA) for p in DATA.rglob("*")) == before  # fixture untouched


def test_importing_ranking_does_not_import_torch() -> None:
    script = "import sys, page_core.ranking\nprint('torch' in sys.modules)\n"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


@pytest.mark.skipif(os.environ.get("PAGE_TEST_SEMANTIC_MODEL") != "1",
                    reason="requires the prepared pretrained model (PAGE_TEST_SEMANTIC_MODEL=1)")
def test_committed_checkpoint_reproduces_the_committed_report() -> None:
    from page_core.semantic import SentenceEncoder

    report = json.loads((Path(__file__).resolve().parents[3] / "benchmarks" / "reranker.json").read_text())
    model = DATA / "model.json"
    assert hashlib.sha256(model.read_bytes()).hexdigest() == report["checkpoint_sha256"]
    result = evaluate(Reranker.load(model), build_candidates(DATA, SentenceEncoder(),
                                                              limit=report["candidates_per_query"]))
    assert {k: result[k] for k in ("baseline", "reranker", "per_query")} == \
        {k: report[k] for k in ("baseline", "reranker", "per_query")}
