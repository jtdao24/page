"""Learned reranking of semantic search candidates (Stage 9).

A small multilayer perceptron reorders Stage 8's cosine-ranked passages using
the baseline score plus lexical, passage-shape and knowledge-graph features.
Training uses PyTorch; inference is plain Python on JSON weights, so loading a
checkpoint never executes code and reranking never imports PyTorch.
"""

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from page_core.domain import validate_note_path
from page_core.graph import GraphSnapshot, build_graph
from page_core.semantic import MAX_TOKENS, Encoder, SearchHit, SemanticIndex

FEATURE_VERSION = "rank-features-v1"
FEATURE_NAMES = (
    "cosine",
    "baseline_reciprocal_rank",
    "gap_to_top",
    "query_terms_in_passage",
    "query_terms_in_path",
    "is_heading",
    "length",
    "is_first_passage",
    "backlinks",
    "links_top_note",
    "links_other_candidates",
)
CHECKPOINT_FORMAT = "page-reranker-v1"
REPORT_FORMAT = "page-reranker-report-v1"
SPLITS = ("train", "test")

_STOPWORDS = frozenset(
    "a an and are as at be by can do does for from how i in is it my of on or should "
    "the to what when where which why will with".split()
)


def _terms(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower())
            if len(word) > 2 and word not in _STOPWORDS}


def _finite_row(row: Sequence[float]) -> tuple[float, ...]:
    values = tuple(float(value) for value in row)
    if len(values) != len(FEATURE_NAMES) or not all(math.isfinite(v) for v in values):
        raise ValueError(f"feature rows need {len(FEATURE_NAMES)} finite values")
    return values


# --- Features -------------------------------------------------------------------


def extract_features(query: str, hits: Sequence[SearchHit],
                     graph: GraphSnapshot) -> list[tuple[float, ...]]:
    """One feature row per candidate, in the given baseline order.

    ``hits`` must be Stage 8 results: sorted by descending cosine score. Pure
    function of its inputs; see FEATURE_NAMES for the meaning of each column.
    """
    if not isinstance(query, str):
        raise TypeError("query must be str")
    if not isinstance(graph, GraphSnapshot):
        raise TypeError("graph must be GraphSnapshot")
    if not all(isinstance(hit, SearchHit) for hit in hits):
        raise TypeError("hits must be SearchHit values")
    if any(later.score > earlier.score for earlier, later in zip(hits, hits[1:])):
        raise ValueError("hits must be in baseline order (descending score)")
    if not hits:
        return []

    neighbors: dict[Any, set[Any]] = {}
    backlinks: dict[Any, set[Any]] = {}
    for edge in graph.links:
        source, target = edge.link.source_note_id, edge.link.target_note_id
        if target is None or target == source:
            continue
        neighbors.setdefault(source, set()).add(target)
        neighbors.setdefault(target, set()).add(source)
        backlinks.setdefault(target, set()).add(source)

    terms = _terms(query)
    top = hits[0].score
    top_note = hits[0].chunk.note_id
    candidate_notes = {hit.chunk.note_id for hit in hits}
    rows = []
    for rank, hit in enumerate(hits, start=1):
        note = hit.chunk.note_id
        linked = neighbors.get(note, set())
        others = candidate_notes - {note}
        path_words = " ".join(hit.relative_path.with_suffix("").parts)
        tokens = hit.chunk.token_count or len(hit.chunk.text.split())
        incoming = len(backlinks.get(note, set()))
        rows.append(_finite_row((
            hit.score,
            1.0 / rank,
            hit.score - top,
            len(terms & _terms(hit.chunk.text)) / len(terms) if terms else 0.0,
            len(terms & _terms(path_words)) / len(terms) if terms else 0.0,
            1.0 if hit.chunk.text.lstrip("﻿ \t").startswith("#") else 0.0,
            min(1.0, math.log1p(tokens) / math.log1p(MAX_TOKENS)),
            1.0 if hit.chunk.ordinal == 0 else 0.0,
            math.log1p(incoming) / (1.0 + math.log1p(incoming)),
            1.0 if note != top_note and top_note in linked else 0.0,
            len(linked & others) / len(others) if others else 0.0,
        )))
    return rows


# --- Model ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankedHit:
    hit: SearchHit
    baseline_rank: int
    score: float


@dataclass(frozen=True, slots=True)
class Reranker:
    """MLP weights: standardize features, one ReLU hidden layer, linear score."""

    mean: tuple[float, ...]
    std: tuple[float, ...]
    hidden_weight: tuple[tuple[float, ...], ...]
    hidden_bias: tuple[float, ...]
    output_weight: tuple[float, ...]
    output_bias: float
    training: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        width = len(FEATURE_NAMES)
        hidden = len(self.hidden_bias)
        shapes_ok = (
            len(self.mean) == len(self.std) == width
            and hidden >= 1
            and len(self.hidden_weight) == hidden
            and all(len(row) == width for row in self.hidden_weight)
            and len(self.output_weight) == hidden
        )
        if not shapes_ok:
            raise ValueError("reranker weights have the wrong shape")
        values = [*self.mean, *self.std, *self.hidden_bias, *self.output_weight, self.output_bias,
                  *(v for row in self.hidden_weight for v in row)]
        if not all(isinstance(v, float) and math.isfinite(v) for v in values):
            raise ValueError("reranker weights must be finite floats")
        if any(v <= 0 for v in self.std):
            raise ValueError("standard deviations must be positive")

    def score(self, row: Sequence[float]) -> float:
        x = [(v - m) / s for v, m, s in zip(_finite_row(row), self.mean, self.std, strict=True)]
        hidden = [max(0.0, b + sum(w * v for w, v in zip(weights, x, strict=True)))
                  for weights, b in zip(self.hidden_weight, self.hidden_bias, strict=True)]
        return self.output_bias + sum(w * h for w, h in zip(self.output_weight, hidden, strict=True))

    def rerank(self, query: str, hits: Sequence[SearchHit], graph: GraphSnapshot) -> tuple[RankedHit, ...]:
        """Hits ordered by neural score; ties keep the baseline order."""
        rows = extract_features(query, hits, graph)
        ranked = [RankedHit(hit, rank, self.score(row))
                  for rank, (hit, row) in enumerate(zip(hits, rows, strict=True), start=1)]
        return tuple(sorted(ranked, key=lambda item: (-item.score, item.baseline_rank)))

    # --- Checkpoints: JSON only, so loading cannot execute code. ---

    def to_json(self) -> dict[str, Any]:
        return {
            "format": CHECKPOINT_FORMAT,
            "feature_version": FEATURE_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "mean": list(self.mean),
            "std": list(self.std),
            "hidden_weight": [list(row) for row in self.hidden_weight],
            "hidden_bias": list(self.hidden_bias),
            "output_weight": list(self.output_weight),
            "output_bias": self.output_bias,
            "training": dict(self.training),
        }

    @classmethod
    def from_json(cls, data: object) -> "Reranker":
        if not isinstance(data, dict):
            raise ValueError("checkpoint must be a JSON object")
        if data.get("format") != CHECKPOINT_FORMAT or data.get("feature_version") != FEATURE_VERSION:
            raise ValueError("unsupported checkpoint format or feature version")
        if data.get("feature_names") != list(FEATURE_NAMES):
            raise ValueError("checkpoint features do not match this version")
        training = data.get("training", {})
        if not isinstance(training, dict):
            raise ValueError("checkpoint training metadata must be an object")

        def floats(value: object) -> tuple[float, ...]:
            if not isinstance(value, list) or not all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
                raise ValueError("checkpoint weights must be lists of numbers")
            return tuple(float(v) for v in value)

        matrix = data.get("hidden_weight")
        if not isinstance(matrix, list):
            raise ValueError("checkpoint hidden_weight must be a list")
        bias = data.get("output_bias")
        if not isinstance(bias, (int, float)) or isinstance(bias, bool):
            raise ValueError("checkpoint output_bias must be a number")
        return cls(floats(data.get("mean")), floats(data.get("std")),
                   tuple(floats(row) for row in matrix), floats(data.get("hidden_bias")),
                   floats(data.get("output_weight")), float(bias),
                   tuple(sorted(training.items())))

    def save(self, path: Path) -> None:
        text = json.dumps(self.to_json(), indent=2, sort_keys=True) + "\n"
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)

    @classmethod
    def load(cls, path: Path) -> "Reranker":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("checkpoint is not valid JSON") from exc
        return cls.from_json(data)


@dataclass(frozen=True, slots=True)
class TrainingGroup:
    """One query's candidates: feature rows and which ones are relevant."""

    features: tuple[tuple[float, ...], ...]
    relevant: tuple[bool, ...]

    def __post_init__(self) -> None:
        if len(self.features) != len(self.relevant):
            raise ValueError("features and labels must have the same length")
        for row in self.features:
            _finite_row(row)
        if not all(isinstance(flag, bool) for flag in self.relevant):
            raise TypeError("labels must be bool")


def train_reranker(groups: Sequence[TrainingGroup], *, hidden: int = 16, epochs: int = 400,
                   learning_rate: float = 0.03, weight_decay: float = 1e-4,
                   seed: int = 0) -> Reranker:
    """Listwise softmax training, deterministic for a given seed and data."""
    usable = [g for g in groups if any(g.relevant) and len(g.relevant) > 1]
    if not usable:
        raise ValueError("no group has a relevant candidate among several")
    import torch

    previous_threads = torch.get_num_threads()
    previous_deterministic = torch.are_deterministic_algorithms_enabled()
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    try:
        torch.manual_seed(seed)
        rows = torch.tensor([row for g in usable for row in g.features], dtype=torch.float64)
        mean = rows.mean(dim=0)
        std = rows.std(dim=0, unbiased=False)
        std = torch.where(std < 1e-6, torch.ones_like(std), std)
        model = torch.nn.Sequential(
            torch.nn.Linear(len(FEATURE_NAMES), hidden), torch.nn.ReLU(), torch.nn.Linear(hidden, 1),
        ).double()
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate, weight_decay=weight_decay)
        batches = [((torch.tensor(g.features, dtype=torch.float64) - mean) / std,
                    torch.tensor(g.relevant, dtype=torch.bool)) for g in usable]
        for _ in range(epochs):
            optimizer.zero_grad()
            loss = torch.zeros((), dtype=torch.float64)
            for features, relevant in batches:
                scores = model(features).squeeze(-1)
                loss = loss + torch.logsumexp(scores, 0) - torch.logsumexp(scores[relevant], 0)
            (loss / len(batches)).backward()
            optimizer.step()
        first, _, second = model
        return Reranker(
            tuple(mean.tolist()), tuple(std.tolist()),
            tuple(tuple(row) for row in first.weight.detach().tolist()),
            tuple(first.bias.detach().tolist()),
            tuple(second.weight.detach()[0].tolist()), float(second.bias.detach()[0]),
            (("epochs", epochs), ("groups", len(usable)), ("hidden", hidden),
             ("learning_rate", learning_rate), ("seed", seed), ("weight_decay", weight_decay)),
        )
    finally:
        torch.use_deterministic_algorithms(previous_deterministic)
        torch.set_num_threads(previous_threads)


# --- Evaluation -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RankingMetrics:
    queries: int
    recall_at_1: float
    recall_at_3: float
    mrr: float


def ranking_metrics(rankings: Sequence[tuple[Sequence[bool], int]]) -> RankingMetrics:
    """Each ranking is (relevance flags in ranked order, number of labeled passages).

    Recall@k counts labeled passages found in the top k; a passage the baseline
    never retrieved counts as missed. MRR uses the first relevant position.
    """
    if not rankings:
        raise ValueError("no rankings to evaluate")
    recall1 = recall3 = reciprocal = 0.0
    for flags, total in rankings:
        if total < 1:
            raise ValueError("each query needs at least one labeled passage")
        recall1 += min(total, sum(flags[:1])) / total
        recall3 += min(total, sum(flags[:3])) / total
        reciprocal += next((1.0 / rank for rank, flag in enumerate(flags, start=1) if flag), 0.0)
    count = len(rankings)
    return RankingMetrics(count, round(recall1 / count, 6), round(recall3 / count, 6),
                          round(reciprocal / count, 6))


# --- Labeled data ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LabeledQuery:
    id: str
    split: str
    query: str
    relevant: tuple[tuple[PurePosixPath, str], ...]

    def matches(self, hit: SearchHit) -> bool:
        return any(hit.relative_path == path and snippet in hit.chunk.text
                   for path, snippet in self.relevant)


def load_queries(path: Path) -> tuple[LabeledQuery, ...]:
    """Strictly validated JSON Lines: id, split, query, relevant[{path, contains}]."""
    queries: list[LabeledQuery] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {number}: invalid JSON") from exc
        if not isinstance(item, dict) or set(item) != {"id", "split", "query", "relevant"}:
            raise ValueError(f"line {number}: expected id, split, query and relevant")
        qid, split, query, relevant = item["id"], item["split"], item["query"], item["relevant"]
        if not all(isinstance(v, str) and v.strip() for v in (qid, split, query)):
            raise ValueError(f"line {number}: id, split and query must be nonblank strings")
        if split not in SPLITS:
            raise ValueError(f"line {number}: split must be train or test")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(f"line {number}: relevant must be a nonempty list")
        passages = []
        for entry in relevant:
            if (not isinstance(entry, dict) or set(entry) != {"path", "contains"}
                    or not isinstance(entry["path"], str) or not isinstance(entry["contains"], str)
                    or not entry["contains"].strip()):
                raise ValueError(f"line {number}: relevant entries need path and contains")
            passages.append((validate_note_path(PurePosixPath(entry["path"])), entry["contains"]))
        queries.append(LabeledQuery(qid, split, query, tuple(passages)))
    if len({q.id for q in queries}) != len(queries):
        raise ValueError("query ids must be unique")
    return tuple(queries)


Candidates = tuple[LabeledQuery, tuple[SearchHit, ...], GraphSnapshot]


def build_candidates(data_dir: Path, encoder: Encoder, *, limit: int = 10) -> list[Candidates]:
    """Index a temporary copy of the fixture vault and retrieve each query's candidates.

    The fixture directory is never modified: Page metadata is created only in
    the temporary copy.
    """
    from page_core.metadata import PersistentVault

    queries = load_queries(data_dir / "queries.jsonl")
    with tempfile.TemporaryDirectory(prefix="page-reranker-") as scratch:
        root = Path(scratch) / "vault"
        shutil.copytree(data_dir / "vault", root)
        with PersistentVault.create(root, "Reranker fixture") as storage:
            notes = tuple(storage.read_note(record.relative_path)
                          for record in storage.metadata.list_notes())
            graph = build_graph(storage.vault.id, notes)
            index = SemanticIndex(storage.metadata, encoder)
            revisions = {note.id: hashlib.sha256(note.content.encode("utf-8")).hexdigest()
                         for note in notes}
            return [(query, index.search(query.query, notes, revisions, limit), graph)
                    for query in queries]


def training_groups(candidates: Iterable[Candidates]) -> list[TrainingGroup]:
    groups = []
    for query, hits, graph in candidates:
        if query.split == "train":
            rows = extract_features(query.query, hits, graph)
            groups.append(TrainingGroup(tuple(rows), tuple(query.matches(hit) for hit in hits)))
    return groups


def evaluate(reranker: Reranker, candidates: Iterable[Candidates], *, split: str = "test") -> dict[str, Any]:
    """Compare baseline and reranked order on one split. Deterministic output."""
    baseline, reranked, per_query = [], [], []
    for query, hits, graph in candidates:
        if query.split != split:
            continue
        flags = [query.matches(hit) for hit in hits]
        order = reranker.rerank(query.query, hits, graph)
        new_flags = [query.matches(item.hit) for item in order]
        total = len(query.relevant)
        baseline.append((flags, total))
        reranked.append((new_flags, total))
        per_query.append({
            "id": query.id,
            "baseline_rank": next((i for i, f in enumerate(flags, 1) if f), None),
            "reranker_rank": next((i for i, f in enumerate(new_flags, 1) if f), None),
        })
    return {
        "split": split,
        "baseline": _metrics_dict(ranking_metrics(baseline)),
        "reranker": _metrics_dict(ranking_metrics(reranked)),
        "per_query": per_query,
    }


def _metrics_dict(metrics: RankingMetrics) -> dict[str, Any]:
    return {"queries": metrics.queries, "recall_at_1": metrics.recall_at_1,
            "recall_at_3": metrics.recall_at_3, "mrr": metrics.mrr}


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from page_core.semantic import FINGERPRINT, SentenceEncoder

    parser = argparse.ArgumentParser(prog="python -m page_core.ranking",
                                     description="Train or evaluate Page's reranker.")
    parser.add_argument("command", choices=["train", "evaluate"])
    parser.add_argument("--data", type=Path, default=Path("training/reranker"))
    parser.add_argument("--model", type=Path, default=Path("training/reranker/model.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/reranker.json"))
    parser.add_argument("--limit", type=int, default=10, help="candidates per query (1-50)")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    candidates = build_candidates(args.data, SentenceEncoder(), limit=args.limit)
    if args.command == "train":
        reranker = train_reranker(training_groups(candidates), seed=args.seed)
        reranker = replace(reranker, training=tuple(sorted(
            reranker.training + (("candidates_per_query", args.limit), ("encoder", FINGERPRINT)))))
        reranker.save(args.model)
        print(f"Saved {args.model} (trained on {dict(reranker.training)['groups']} queries).")
        return 0
    reranker = Reranker.load(args.model)
    report = {
        "format": REPORT_FORMAT,
        "checkpoint_sha256": _sha256(args.model),
        "encoder": FINGERPRINT,
        "feature_version": FEATURE_VERSION,
        "candidates_per_query": args.limit,
        **evaluate(reranker, candidates),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("baseline", "reranker")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
