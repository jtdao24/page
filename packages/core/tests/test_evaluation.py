"""Stage 11 benchmark harness: data, readers, systems and report, offline."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from page_core.context import Utf8TokenEstimate
from page_core.evaluation import (
    SYSTEMS, ExtractiveAnswerer, contains_answer, full_context, indexed_copy, load_questions,
    run_benchmark, summary_markdown,
)
from page_core.ranking import Reranker
from test_ranking import random_reranker

ROOT = Path(__file__).resolve().parents[3]
EVAL = ROOT / "benchmarks" / "eval"


class EvalKeywordEncoder:
    """Offline stand-in for MiniLM over the evaluation vault's topics."""

    fingerprint = "test-eval-keyword-encoder-v1"
    dimension = 9
    TOPICS = ("tap|washer|leak|drip|water", "heater|thermostat|tank|sediment", "paint|primer|coat|wall",
              "tyre|tire|puncture|tube|pressure", "chain|lubricant|cassette", "coffee|espresso|grind|burr|brew",
              "budget|savings|fund|income|money", "aperture|shutter|iso|frame|photo", "bird|feeder|seed|song")

    def offsets(self, text: str) -> list[tuple[int, int]]:
        return [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]

    def encode(self, texts):
        return [[float(len(re.findall(topic, text.lower()))) for topic in self.TOPICS] for text in texts]

    # A zero vector is invalid for the index, so give every text a small bias.
    def __init__(self):
        original = self.encode
        self.encode = lambda texts: [[*row[:-1], row[-1] + 0.1] for row in original(texts)]


def test_questions_are_strictly_validated(tmp_path: Path) -> None:
    good = {"id": "e", "question": "q", "answer": "a", "relevant": [{"path": "a.md", "contains": "a"}]}
    for bad in ({**good, "answer": " "}, {**good, "extra": 1}, {**good, "relevant": []},
                {**good, "relevant": [{"path": "/a.md", "contains": "a"}]}):
        (tmp_path / "q.jsonl").write_text(json.dumps(bad) + "\n")
        with pytest.raises(ValueError):
            load_questions(tmp_path / "q.jsonl")
    (tmp_path / "q.jsonl").write_text(json.dumps(good) + "\n" + json.dumps(good) + "\n")
    with pytest.raises(ValueError, match="unique"):
        load_questions(tmp_path / "q.jsonl")


def test_evaluation_dataset_is_consistent_and_separate_from_training() -> None:
    questions = load_questions(EVAL / "questions.jsonl")
    assert len(questions) >= 30
    for question in questions:
        for path, snippet in question.relevant:
            text = (EVAL / "vault" / path).read_text(encoding="utf-8")
            paragraph = next(p for p in text.split("\n\n") if snippet in p)
            assert contains_answer(paragraph, question.answer), question.id
    training = {p.name for p in (ROOT / "training" / "reranker" / "vault").rglob("*.md")}
    evaluation = {p.name for p in (EVAL / "vault").rglob("*.md")}
    assert not training & evaluation  # no note is shared with the reranker's training data


def test_extractive_answerer() -> None:
    reader = ExtractiveAnswerer()
    context = ("[1] coffee/espresso.md (lines 3-5)\nA double shot uses eighteen grams. "
               "Aim for twenty-five seconds.\n\n[2] coffee/pour-over.md (line 3, excerpt)\nRinse the filter … Bloom first.\n")
    assert reader.answer("how many grams for a double shot", context) == "A double shot uses eighteen grams."
    assert reader.answer("pour over filter rinse", context) == "Rinse the filter"
    assert reader.answer("coffee espresso", "[1] coffee/espresso.md (line 1)\n") == ""  # headers are skipped
    assert reader.answer("anything", "") == ""


def test_answer_matching_ignores_case_and_spacing() -> None:
    assert contains_answer("Keep  THREE to six\nmonths saved.", "three to six months")
    assert not contains_answer("three months", "three to six months")


def test_full_context_contains_every_note() -> None:
    with indexed_copy(EVAL / "vault", EvalKeywordEncoder()) as (notes, _, _):
        built = full_context(notes, Utf8TokenEstimate())
    assert len(built.cited) == len(notes) == len(list((EVAL / "vault").rglob("*.md")))
    assert all(note.content.strip() in built.text for note in notes)
    assert built.tokens == Utf8TokenEstimate().count(built.text)


def run(**kwargs):
    return run_benchmark(EVAL, EvalKeywordEncoder(), random_reranker(), candidates=5,
                         sweep=(50, 200), **kwargs)


def test_benchmark_report_is_complete_and_consistent() -> None:
    before = sorted(p.relative_to(EVAL) for p in EVAL.rglob("*"))
    report = run(budget=200, top_k=3)

    assert sorted(p.relative_to(EVAL) for p in EVAL.rglob("*")) == before  # fixture untouched
    assert report["dataset"]["questions"] == len(report["per_question"]) == len(load_questions(EVAL / "questions.jsonl"))
    assert set(report["systems"]) == set(SYSTEMS)
    full = report["systems"]["full_context"]
    assert full["answer_support"] == 1.0 and full["attribution_recall"] == 1.0
    assert full["token_reduction_vs_full"] == 0.0
    for name in ("page_cosine", "page_reranked"):
        assert report["systems"][name]["avg_tokens"] <= 200
        assert all(row[name]["tokens"] <= 200 for row in report["per_question"])
    for metrics in report["systems"].values():
        for key in ("answer_support", "answer_accuracy", "attribution_precision", "attribution_recall"):
            assert 0.0 <= metrics[key] <= 1.0
    for order in ("embedding", "reranked"):
        recalls = [report["retrieval"][order][f"recall_at_{k}"] for k in (1, 3, 5, 10)]
        assert recalls == sorted(recalls)
    assert {(r["system"], r["budget"]) for r in report["budget_sweep"]} == {
        (s, b) for s in ("page_cosine", "page_reranked") for b in (50, 200)}
    assert set(report["latency_ms"]) == {"search", *SYSTEMS}
    assert "| Page optimizer, reranked |" in summary_markdown(report)


def test_benchmark_is_deterministic_apart_from_latency() -> None:
    first, second = run(), run()
    first.pop("latency_ms"), second.pop("latency_ms")
    assert first == second


def test_a_custom_reader_is_used() -> None:
    class EchoReader:
        name = "echo"

        def answer(self, question: str, context: str) -> str:
            return context

    report = run(answerer=EchoReader())
    assert report["answerer"] == "echo"
    for metrics in report["systems"].values():
        assert metrics["answer_accuracy"] == metrics["answer_support"]


def test_importing_evaluation_does_not_import_torch() -> None:
    script = "import sys, page_core.evaluation\nprint('torch' in sys.modules)\n"
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


@pytest.mark.skipif(os.environ.get("PAGE_TEST_SEMANTIC_MODEL") != "1",
                    reason="requires the prepared pretrained model (PAGE_TEST_SEMANTIC_MODEL=1)")
def test_committed_report_is_reproducible() -> None:
    from page_core.semantic import SentenceEncoder

    committed = json.loads((ROOT / "benchmarks" / "results" / "stage11.json").read_text())
    settings = committed["settings"]
    fresh = run_benchmark(EVAL, SentenceEncoder(), Reranker.load(ROOT / "training" / "reranker" / "model.json"),
                          budget=settings["budget"], top_k=settings["top_k"], candidates=settings["candidates"])
    committed.pop("latency_ms"), fresh.pop("latency_ms")
    assert fresh == committed
