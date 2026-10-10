"""Benchmark: does Page's context optimization save tokens without losing answers?

Compares four ways of building LLM context for the same held-out questions:

- ``full_context``: every note in the vault;
- ``embedding_top_k``: semantic search's top-k passages, whole;
- ``page_cosine``: context optimization ranked by embedding cosine;
- ``page_reranked``: context optimization ranked by the learned reranker.

Each is measured on input tokens, whether the context contains the answer, whether
a reader answers correctly from it, and whether the cited sources are right.
Retrieval itself is measured with recall@k and MRR. No LLM is called here: the
default reader is an offline extractive one, and an LLM reader can be plugged in
through ``Answerer``.
"""

import hashlib
import json
import re
import statistics
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from page_core.context import TokenCounter, Utf8TokenEstimate, optimize_context
from page_core.domain import Note, validate_note_path
from page_core.graph import GraphSnapshot, build_graph
from page_core.ranking import Reranker, fixture_copy, text_terms
from page_core.semantic import Encoder, SearchHit, SemanticIndex

REPORT_FORMAT = "page-benchmark-v1"
SYSTEMS = ("full_context", "embedding_top_k", "page_cosine", "page_reranked")
RECALL_AT = (1, 3, 5, 10)


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    id: str
    question: str
    answer: str
    relevant: tuple[tuple[PurePosixPath, str], ...]

    def matches(self, hit: SearchHit) -> bool:
        return any(hit.relative_path == path and snippet in hit.chunk.text
                   for path, snippet in self.relevant)

    @property
    def relevant_paths(self) -> frozenset[PurePosixPath]:
        return frozenset(path for path, _ in self.relevant)


def load_questions(path: Path) -> tuple[EvalQuestion, ...]:
    """Strict JSON Lines: id, question, answer, relevant[{path, contains}]."""
    questions = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {number}: invalid JSON") from exc
        if not isinstance(item, dict) or set(item) != {"id", "question", "answer", "relevant"}:
            raise ValueError(f"line {number}: expected id, question, answer and relevant")
        values = (item["id"], item["question"], item["answer"])
        if not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError(f"line {number}: id, question and answer must be nonblank strings")
        relevant = item["relevant"]
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(f"line {number}: relevant must be a nonempty list")
        passages = []
        for entry in relevant:
            if (not isinstance(entry, dict) or set(entry) != {"path", "contains"}
                    or not isinstance(entry["path"], str) or not isinstance(entry["contains"], str)
                    or not entry["contains"].strip()):
                raise ValueError(f"line {number}: relevant entries need path and contains")
            passages.append((validate_note_path(PurePosixPath(entry["path"])), entry["contains"]))
        questions.append(EvalQuestion(*values, tuple(passages)))
    if len({q.id for q in questions}) != len(questions):
        raise ValueError("question ids must be unique")
    return tuple(questions)


# --- Readers ---------------------------------------------------------------------


class Answerer(Protocol):
    name: str

    def answer(self, question: str, context: str) -> str: ...


_HEADER = re.compile(r"^\[\d+\] .+\)$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\s+…\s+|\r\n|\r|\n")


class ExtractiveAnswerer:
    """Offline reader: returns the context sentence sharing most words with the question.

    A deliberately simple stand-in for an LLM. It gets worse when relevant text is
    buried among many similar sentences, which is the effect context selection
    is meant to reduce. Ties go to the earliest sentence.
    """

    name = "extractive-overlap-v1"

    def answer(self, question: str, context: str) -> str:
        terms = text_terms(question)
        best, best_score = "", 0
        for line in context.splitlines():
            if _HEADER.match(line):
                continue
            for sentence in _SENTENCE.split(line):
                score = len(terms & text_terms(sentence))
                if score > best_score:
                    best, best_score = sentence.strip(), score
        return best


def _normalized(text: str) -> str:
    return " ".join(text.lower().split())


def contains_answer(text: str, answer: str) -> bool:
    return _normalized(answer) in _normalized(text)


# --- Systems ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuiltContext:
    text: str
    cited: tuple[PurePosixPath, ...]
    tokens: int


def full_context(notes: Sequence[Note], counter: TokenCounter) -> BuiltContext:
    """Every note, whole, in path order, in the same block format as the context optimizer."""
    ordered = sorted(notes, key=lambda note: str(note.relative_path))
    text = "\n\n".join(f"[{i}] {note.relative_path} (whole note)\n{note.content.strip()}"
                       for i, note in enumerate(ordered, start=1))
    text = text + "\n" if text else ""
    return BuiltContext(text, tuple(note.relative_path for note in ordered), counter.count(text))


def _package(question: str, hits: Sequence[SearchHit], graph: GraphSnapshot, counter: TokenCounter,
             **options: Any) -> BuiltContext:
    package = optimize_context(question, hits, graph, counter=counter, **options)
    return BuiltContext(package.result.context_text,
                        tuple(block.relative_path for block in package.blocks),
                        package.result.token_count)


def build_systems(budget: int, top_k: int, reranker: Reranker
                  ) -> dict[str, Callable[[str, Sequence[SearchHit], GraphSnapshot, TokenCounter], BuiltContext]]:
    """Retrieval-based systems keyed by name; full context is built separately."""
    return {
        # Plain top-k: no relevance cutoff, deduplication of exact repeats only, no diversity.
        "embedding_top_k": lambda q, h, g, c: _package(
            q, h, g, c, budget=10**9, max_passages=top_k, min_relevance=0.0, redundancy_threshold=1.0,
            diversity=0.0, coverage_weight=0.0, graph_weight=0.0),
        "page_cosine": lambda q, h, g, c: _package(q, h, g, c, budget=budget),
        "page_reranked": lambda q, h, g, c: _package(q, h, g, c, budget=budget, reranker=reranker),
    }


# --- Running ---------------------------------------------------------------------


@contextmanager
def indexed_copy(vault_dir: Path, encoder: Encoder) -> Iterator[tuple[tuple[Note, ...], GraphSnapshot, Callable[[str, int], tuple[SearchHit, ...]]]]:
    """Index a temporary copy of a fixture vault with deterministic IDs.

    Yields the notes, their link graph, and a search function. The fixture
    directory itself is never modified.
    """
    with fixture_copy(vault_dir, "Benchmark fixture") as storage:
        notes = tuple(storage.read_note(record.relative_path) for record in storage.metadata.list_notes())
        graph = build_graph(storage.vault.id, notes)
        index = SemanticIndex(storage.metadata, encoder)
        index.update(notes)
        revisions = {note.id: hashlib.sha256(note.content.encode("utf-8")).hexdigest() for note in notes}

        def search(query: str, limit: int) -> tuple[SearchHit, ...]:
            return index.search(query, notes, revisions, limit)

        yield notes, graph, search


def _recall(flags: Sequence[bool], total: int, k: int) -> float:
    return min(total, sum(flags[:k])) / total


def _retrieval_metrics(rankings: Sequence[Sequence[bool]], totals: Sequence[int]) -> dict[str, float]:
    metrics = {f"recall_at_{k}": _mean([_recall(flags, total, k) for flags, total in zip(rankings, totals)])
               for k in RECALL_AT}
    metrics["mrr"] = _mean([next((1 / rank for rank, flag in enumerate(flags, 1) if flag), 0.0)
                            for flags in rankings])
    return metrics


def _mean(values: Sequence[float]) -> float:
    return round(statistics.fmean(values), 6) if values else 0.0


def _fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def run_benchmark(data_dir: Path, encoder: Encoder, reranker: Reranker, *, budget: int = 300,
                  top_k: int = 5, candidates: int = 10, sweep: Sequence[int] = (100, 300, 1000),
                  answerer: Answerer | None = None, counter: TokenCounter | None = None) -> dict[str, Any]:
    """Run every system on every question. Only ``latency_ms`` depends on the machine."""
    answerer = answerer or ExtractiveAnswerer()
    counter = counter or Utf8TokenEstimate()
    questions = load_questions(data_dir / "questions.jsonl")
    systems = build_systems(budget, top_k, reranker)
    rows: dict[str, list[dict[str, Any]]] = {name: [] for name in SYSTEMS}
    retrieval: dict[str, list[list[bool]]] = {"embedding": [], "reranked": []}
    totals, latency, per_question = [], {name: [] for name in ("search", *SYSTEMS)}, []
    sweep_rows: dict[tuple[str, int], list[dict[str, Any]]] = {}

    def score(built: BuiltContext, question: EvalQuestion) -> dict[str, Any]:
        cited = built.cited
        relevant = sum(path in question.relevant_paths for path in cited)
        return {
            "tokens": built.tokens,
            "supported": contains_answer(built.text, question.answer),
            "correct": contains_answer(answerer.answer(question.question, built.text), question.answer),
            "precision": relevant / len(cited) if cited else 0.0,
            "recall": 1.0 if relevant else 0.0,
        }

    with indexed_copy(data_dir / "vault", encoder) as (notes, graph, search):
        started = time.perf_counter()
        full = full_context(notes, counter)
        full_ms = (time.perf_counter() - started) * 1000
        for question in questions:
            started = time.perf_counter()
            hits = search(question.question, candidates)
            latency["search"].append((time.perf_counter() - started) * 1000)
            totals.append(len(question.relevant))
            retrieval["embedding"].append([question.matches(hit) for hit in hits])
            retrieval["reranked"].append([question.matches(item.hit)
                                          for item in reranker.rerank(question.question, hits, graph)])
            result = {"full_context": score(full, question)}
            latency["full_context"].append(full_ms)
            for name, system in systems.items():
                started = time.perf_counter()
                built = system(question.question, hits, graph, counter)
                latency[name].append((time.perf_counter() - started) * 1000)
                result[name] = score(built, question)
            for name in SYSTEMS:
                rows[name].append(result[name])
            for size in sweep:
                for name, options in (("page_cosine", {}), ("page_reranked", {"reranker": reranker})):
                    built = _package(question.question, hits, graph, counter, budget=size, **options)
                    sweep_rows.setdefault((name, size), []).append(score(built, question))
            per_question.append({"id": question.id, **{
                name: {k: result[name][k] for k in ("tokens", "supported", "correct")} for name in SYSTEMS}})

    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "avg_tokens": _mean([r["tokens"] for r in items]),
            "answer_support": _mean([float(r["supported"]) for r in items]),
            "answer_accuracy": _mean([float(r["correct"]) for r in items]),
            "attribution_precision": _mean([r["precision"] for r in items]),
            "attribution_recall": _mean([r["recall"] for r in items]),
        }

    summary = {name: summarize(rows[name]) for name in SYSTEMS}
    full_tokens = summary["full_context"]["avg_tokens"]
    for name in SYSTEMS:
        summary[name]["token_reduction_vs_full"] = (
            round(1 - summary[name]["avg_tokens"] / full_tokens, 6) if full_tokens else 0.0)
    return {
        "format": REPORT_FORMAT,
        "dataset": {"questions": len(questions), "notes": len(notes),
                    "sha256": _fingerprint(data_dir)},
        "encoder": getattr(encoder, "fingerprint", "unknown"),
        "reranker_training": dict(reranker.training),
        "counter": counter.name,
        "answerer": answerer.name,
        "settings": {"budget": budget, "top_k": top_k, "candidates": candidates},
        "retrieval": {order: _retrieval_metrics(flags, totals) for order, flags in retrieval.items()},
        "systems": summary,
        "budget_sweep": [
            {"system": name, "budget": size,
             **{k: v for k, v in summarize(items).items() if k in ("avg_tokens", "answer_support", "answer_accuracy")}}
            for (name, size), items in sorted(sweep_rows.items(), key=lambda kv: (kv[0][0], kv[0][1]))
        ],
        "per_question": per_question,
        "latency_ms": {name: {"median": round(statistics.median(values), 3),
                              "max": round(max(values), 3)} for name, values in latency.items() if values},
    }


def summary_markdown(report: dict[str, Any]) -> str:
    """A short human-readable summary of a report."""
    s = report["systems"]
    labels = {"full_context": "Full context (all notes)", "embedding_top_k": "Embedding top-k",
              "page_cosine": "Page optimizer, cosine", "page_reranked": "Page optimizer, reranked"}
    lines = [
        "# Benchmark results",
        "",
        f"{report['dataset']['questions']} held-out questions over {report['dataset']['notes']} notes. "
        f"Budget {report['settings']['budget']} tokens for the Page optimizer, top "
        f"{report['settings']['top_k']} for embedding retrieval, {report['settings']['candidates']} "
        f"candidates per question. Tokens: `{report['counter']}`. Reader: `{report['answerer']}`.",
        "",
        "| System | Avg input tokens | Token reduction vs full | Answer in context | Reader correct | Source precision |",
        "|---|---|---|---|---|---|",
    ]
    for name in SYSTEMS:
        row = s[name]
        lines.append(f"| {labels[name]} | {row['avg_tokens']:.0f} | {row['token_reduction_vs_full']:.0%} | "
                     f"{row['answer_support']:.0%} | {row['answer_accuracy']:.0%} | "
                     f"{row['attribution_precision']:.0%} |")
    lines += ["", "| Retrieval order | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |", "|---|---|---|---|---|---|"]
    for order, label in (("embedding", "Embedding"), ("reranked", "Reranked")):
        r = report["retrieval"][order]
        lines.append(f"| {label} | {r['recall_at_1']:.3f} | {r['recall_at_3']:.3f} | {r['recall_at_5']:.3f} | "
                     f"{r['recall_at_10']:.3f} | {r['mrr']:.3f} |")
    lines += ["", "| Budget | System | Avg tokens | Answer in context | Reader correct |", "|---|---|---|---|---|"]
    for row in report["budget_sweep"]:
        lines.append(f"| {row['budget']} | {labels[row['system']]} | {row['avg_tokens']:.0f} | "
                     f"{row['answer_support']:.0%} | {row['answer_accuracy']:.0%} |")
    lines += ["", "Latency on the machine that produced this report (median ms per question): "
              + ", ".join(f"{name} {values['median']:.1f}" for name, values in report["latency_ms"].items())
              + ".", ""]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from page_core.semantic import SentenceEncoder

    parser = argparse.ArgumentParser(prog="python -m page_core.evaluation",
                                     description="Run Page's context benchmark.")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--data", type=Path, default=Path("benchmarks/eval"))
    parser.add_argument("--model", type=Path, default=Path("training/reranker/model.json"))
    parser.add_argument("--report", type=Path, default=Path("benchmarks/results/evaluation.json"))
    parser.add_argument("--summary", type=Path, default=Path("benchmarks/results/evaluation.md"))
    parser.add_argument("--budget", type=int, default=300)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidates", type=int, default=10)
    args = parser.parse_args(argv)

    report = run_benchmark(args.data, SentenceEncoder(), Reranker.load(args.model), budget=args.budget,
                           top_k=args.top_k, candidates=args.candidates)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.summary.write_text(summary_markdown(report), encoding="utf-8")
    print(summary_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
