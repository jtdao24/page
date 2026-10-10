"""Token-budgeted, source-attributed context packages.

``optimize_context`` turns ranked search candidates into the smallest useful
context for an LLM: it drops duplicates, prefers passages that add something new,
favors notes linked to what is already chosen, trims oversized passages to their
most relevant sentences, and never exceeds the token budget. Every block keeps
exact source references. Pure and deterministic: no I/O, models or PyTorch.
"""

import hashlib
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Protocol
from uuid import UUID, uuid5

from page_core.domain import Chunk, ContextResult
from page_core.graph import GraphSnapshot
from page_core.ranking import Reranker, text_terms
from page_core.semantic import SearchHit


class TokenCounter(Protocol):
    name: str

    def count(self, text: str) -> int: ...


class Utf8TokenEstimate:
    """Conservative estimate: one token per three UTF-8 bytes, rounded up.

    Common LLM tokenizers average about four characters per token on English
    text, so this overestimates and keeps packages within real budgets. Exact
    provider counters can replace it.
    """

    name = "utf8-bytes/3"

    def count(self, text: str) -> int:
        return math.ceil(len(text.encode("utf-8")) / 3)


@dataclass(frozen=True, slots=True)
class ContextBlock:
    number: int
    note_id: UUID
    relative_path: PurePosixPath
    start_line: int
    end_line: int
    chunks: tuple[Chunk, ...]
    text: str
    relevance: float
    compressed: bool


@dataclass(frozen=True, slots=True)
class ContextUsage:
    counter: str
    budget: int
    tokens: int
    candidate_tokens: int
    considered: int
    selected: int
    compressed: int
    dropped_redundant: int
    dropped_budget: int
    dropped_relevance: int
    dropped_limit: int


@dataclass(frozen=True, slots=True)
class ContextPackage:
    result: ContextResult
    blocks: tuple[ContextBlock, ...]
    usage: ContextUsage


@dataclass(frozen=True, slots=True)
class _Candidate:
    order: int
    hit: SearchHit
    relevance: float
    terms: frozenset[str]
    digest: str


_LINE_BREAK = re.compile(r"\r\n|\r|\n")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])[ \t]+|\r\n|\r|\n")


def _breaks(text: str) -> int:
    return len(_LINE_BREAK.findall(text))


def _similarity(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0


def _render(blocks: Sequence[ContextBlock]) -> str:
    parts = []
    for block in blocks:
        lines = (f"line {block.start_line}" if block.start_line == block.end_line
                 else f"lines {block.start_line}-{block.end_line}")
        excerpt = ", excerpt" if block.compressed else ""
        parts.append(f"[{block.number}] {block.relative_path} ({lines}{excerpt})\n{block.text}")
    return "\n\n".join(parts) + ("\n" if parts else "")


def _check_fraction(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
    return float(value)


def _whole_block(candidate: _Candidate, number: int) -> ContextBlock:
    # Lines describe the text shown: the passage without its surrounding blank lines.
    hit = candidate.hit
    text = hit.chunk.text
    shown = text.strip()
    start = hit.start_line + _breaks(text[:len(text) - len(text.lstrip())])
    return ContextBlock(number, hit.chunk.note_id, hit.relative_path, start, start + _breaks(shown),
                        (hit.chunk,), shown, candidate.relevance, False)


def _sentences(text: str) -> list[tuple[int, int]]:
    """Character spans of sentences and lines, trimmed of surrounding whitespace."""
    spans, start = [], 0
    for match in _SENTENCE_BREAK.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    trimmed = []
    for a, b in spans:
        while a < b and text[a].isspace():
            a += 1
        while b > a and text[b - 1].isspace():
            b -= 1
        if b > a:
            trimmed.append((a, b))
    return trimmed


def _excerpt(candidate: _Candidate, number: int, query_terms: frozenset[str],
             fits: Callable[[ContextBlock], bool]) -> ContextBlock | None:
    """The passage's most query-relevant sentences, in source order, if any fit."""
    hit = candidate.hit
    chunk, text = hit.chunk, hit.chunk.text
    scored = [(len(query_terms & text_terms(text[a:b])), index, (a, b))
              for index, (a, b) in enumerate(_sentences(text))]
    ranked = sorted((item for item in scored if item[0] > 0), key=lambda item: (-item[0], item[1]))
    if len(scored) < 2 or not ranked:
        return None

    def block(spans: list[tuple[int, int]]) -> ContextBlock:
        spans = sorted(spans)
        chunks = tuple(
            Chunk(uuid5(chunk.id, f"extract:{a}:{b}"), chunk.note_id, chunk.ordinal, text[a:b],
                  chunk.start_byte + len(text[:a].encode("utf-8")),
                  chunk.start_byte + len(text[:b].encode("utf-8")), None)
            for a, b in spans)
        first, last = spans[0][0], spans[-1][1]
        return ContextBlock(number, chunk.note_id, hit.relative_path,
                            hit.start_line + _breaks(text[:first]), hit.start_line + _breaks(text[:last]),
                            chunks, " … ".join(text[a:b] for a, b in spans), candidate.relevance, True)

    kept: list[tuple[int, int]] = []
    for _, _, span in ranked:
        trial = block(kept + [span])
        if fits(trial):
            kept.append(span)
    if not kept or len(kept) == len(scored):
        return None
    return block(kept)


def optimize_context(
    query: str,
    hits: Sequence[SearchHit],
    graph: GraphSnapshot,
    *,
    budget: int,
    counter: TokenCounter | None = None,
    reranker: Reranker | None = None,
    max_passages: int = 8,
    min_relevance: float = 0.25,
    redundancy_threshold: float = 0.8,
    diversity: float = 0.3,
    coverage_weight: float = 0.2,
    graph_weight: float = 0.1,
) -> ContextPackage:
    """Select a source-attributed context package that fits ``budget`` tokens.

    ``hits`` are semantic search results in baseline order. With a reranker, its
    scores rank them; otherwise cosine scores do. Relevance is measured relative
    to the best candidate (1.0) before thresholds and weights apply.
    """
    if not isinstance(query, str):
        raise TypeError("query must be str")
    if not isinstance(graph, GraphSnapshot):
        raise TypeError("graph must be GraphSnapshot")
    if not all(isinstance(hit, SearchHit) for hit in hits):
        raise TypeError("hits must be SearchHit values")
    if any(later.score > earlier.score for earlier, later in zip(hits, hits[1:])):
        raise ValueError("hits must be in baseline order (descending score)")
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("budget must be int")
    if budget < 1:
        raise ValueError("budget must be positive")
    if isinstance(max_passages, bool) or not isinstance(max_passages, int):
        raise TypeError("max_passages must be int")
    if max_passages < 1:
        raise ValueError("max_passages must be positive")
    if reranker is not None and not isinstance(reranker, Reranker):
        raise TypeError("reranker must be a Reranker or None")
    min_relevance = _check_fraction("min_relevance", min_relevance)
    redundancy_threshold = _check_fraction("redundancy_threshold", redundancy_threshold)
    diversity = _check_fraction("diversity", diversity)
    coverage_weight = _check_fraction("coverage_weight", coverage_weight)
    graph_weight = _check_fraction("graph_weight", graph_weight)
    counter = counter or Utf8TokenEstimate()
    if not isinstance(getattr(counter, "name", None), str) or not callable(getattr(counter, "count", None)):
        raise TypeError("counter must have a name and a count(text) method")

    def tokens(text: str) -> int:
        value = counter.count(text)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("token counter must return a nonnegative int")
        return value

    # Relevance relative to the best candidate, so the top scores 1 and close
    # runners-up stay close to 1. Reranker scores are unbounded: exp(score - top).
    # Cosine scores: cosine / top cosine, with non-positive scores at 0.
    if reranker is not None:
        ranked = [(item.hit, item.score) for item in reranker.rerank(query, hits, graph)]
        top = max((score for _, score in ranked), default=0.0)
        ordered = [(hit, math.exp(score - top)) for hit, score in ranked]
    else:
        top = hits[0].score if hits else 0.0
        ordered = [(hit, max(0.0, hit.score) / top if top > 1e-9 else 0.0) for hit in hits]
    candidates = [
        _Candidate(order, hit, min(1.0, relevance),
                   frozenset(text_terms(hit.chunk.text)),
                   hashlib.sha256(" ".join(hit.chunk.text.split()).encode("utf-8")).hexdigest())
        for order, (hit, relevance) in enumerate(ordered)
    ]

    neighbors: dict[UUID, set[UUID]] = {}
    for edge in graph.links:
        source, target = edge.link.source_note_id, edge.link.target_note_id
        if target is not None and target != source:
            neighbors.setdefault(source, set()).add(target)
            neighbors.setdefault(target, set()).add(source)

    query_terms = frozenset(text_terms(query))
    candidate_tokens = tokens(_render([_whole_block(c, i) for i, c in enumerate(candidates, 1)]))
    eligible = [c for c in candidates if c.relevance >= min_relevance]
    dropped_relevance = len(candidates) - len(eligible)
    blocks: list[ContextBlock] = []
    chosen: list[_Candidate] = []
    covered: set[str] = set()
    redundant = over_budget = 0

    def fits(block: ContextBlock) -> bool:
        return tokens(_render([*blocks, block])) <= budget

    def marginal(candidate: _Candidate) -> float:
        overlap = max((_similarity(candidate.terms, other.terms) for other in chosen), default=0.0)
        new_terms = len((query_terms & candidate.terms) - covered) / len(query_terms) if query_terms else 0.0
        chosen_notes = {other.hit.chunk.note_id for other in chosen}
        note = candidate.hit.chunk.note_id
        linked = 1.0 if neighbors.get(note, set()) & (chosen_notes - {note}) else 0.0
        return ((1 - diversity) * candidate.relevance - diversity * overlap
                + coverage_weight * new_terms + graph_weight * linked)

    remaining = list(eligible)
    while remaining and len(blocks) < max_passages:
        best = max(remaining, key=lambda c: (marginal(c), -c.order))
        remaining.remove(best)
        if any(best.digest == other.digest or
               _similarity(best.terms, other.terms) >= redundancy_threshold for other in chosen):
            redundant += 1
            continue
        number = len(blocks) + 1
        whole = _whole_block(best, number)
        block = whole if fits(whole) else _excerpt(best, number, query_terms, fits)
        if block is None:
            over_budget += 1
            continue
        blocks.append(block)
        chosen.append(best)
        covered |= query_terms & best.terms

    text = _render(blocks)
    result = ContextResult(text, tuple(chunk for block in blocks for chunk in block.chunks),
                           tokens(text), budget)
    usage = ContextUsage(
        counter.name, budget, result.token_count, candidate_tokens, len(candidates), len(blocks),
        sum(block.compressed for block in blocks), redundant, over_budget, dropped_relevance,
        len(remaining),
    )
    return ContextPackage(result, tuple(blocks), usage)
