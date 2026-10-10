# Evaluation and benchmarking

This benchmark tests Page's central question on held-out data: can context selection cut
LLM input tokens while keeping the information needed to answer? The code is
`page_core.evaluation`; the data and results are in `benchmarks/`.

## What is compared

Each question's context is built four ways:

| System | What goes to the model |
|---|---|
| `full_context` | Every note in the vault, whole |
| `embedding_top_k` | Semantic search's 5 most similar passages, whole |
| `page_cosine` | Context optimizer (300-token budget), ranked by embedding similarity |
| `page_reranked` | Context optimizer (300-token budget), ranked by the learned reranker |

Retrieval is also measured on its own: recall@1/3/5/10 and mean reciprocal rank for
the embedding order and for the reranker's order, over 10 candidates.

## Data

`benchmarks/eval/` is separate from the reranker's training data:
- **Vault:** 17 notes on home repair, cycling, coffee, personal finance, photography,
  first aid, music and birdwatching, with wiki links. None of these notes appear in
  `training/reranker/`, and a test enforces that.
- **Questions:** 40 in `questions.jsonl`, each with a short gold answer and the passage
  that contains it. A test checks every answer is in its labeled passage.

The benchmark runs on a temporary copy of the vault with Page's real storage and the
real pinned MiniLM model. Vault and note IDs are assigned deterministically, so two runs
give identical results, apart from latency.

## Metrics

- **Avg input tokens:** with the default `utf8-bytes/3` estimate (see
  [context optimization](context-optimization.md)).
- **Token reduction:** relative to full context.
- **Answer in context:** the gold answer appears in the context. An upper bound for any
  reader.
- **Reader correct:** an answer extracted from the context contains the gold answer.
  The default reader (`extractive-overlap-v1`) picks the sentence sharing the most
  words with the question. It needs no LLM. An LLM can be
  plugged in through the `Answerer` protocol.
- **Source precision / recall:** the share of cited notes that contain the answer, and
  whether any cited note does.
- **Latency:** per-question search and packaging time on the machine that ran it.
  Informational only.

## Results

Produced by `python -m page_core.evaluation run` on macOS, October 10, 2026
(`benchmarks/results/evaluation.json`, summary in `evaluation.md`):

| System | Avg tokens | Saved vs. full | Answer in context | Reader correct | Source precision |
|---|---|---|---|---|---|
| Full context | 2606 | 0% | 100% | 62% | 6% |
| Embedding top-5 | 199 | 92% | 100% | 72% | 64% |
| Page optimizer, cosine | 267 | 90% | 100% | 75% | 57% |
| Page optimizer, reranked | 43 | 98% | 72% | 68% | 92% |

| Retrieval order | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| Embedding | 0.775 | 1.000 | 1.000 | 1.000 | 0.875 |
| Reranker | 0.700 | 0.875 | 0.925 | 1.000 | 0.799 |

## What the results show

1. **Context selection works on unseen data.** The cosine-ranked optimizer used 90%
   fewer tokens than sending every note, and the answer was still in the context for
   all 40 questions. The reader was also more accurate with it (75%) than with full
   context (62%), because there were fewer similar-but-wrong sentences to choose from.
2. **The learned reranker does not generalize.** On notes it never trained on, it
   ranks worse than plain embedding similarity: recall@1 drops from 0.775 to 0.700 and
   MRR from 0.875 to 0.799. Its sharply separated scores also make the optimizer keep
   very little (43 tokens on average), so the answer is missing from the context for
   28% of questions. The gains reported for the reranker and optimizer came from a tiny training
   set evaluated close to its own data, which is overfitting.
3. **Plain top-5 retrieval is a strong baseline.** On this vault it matches the
   optimizer's answer coverage with fewer tokens (199 vs. 267). The optimizer's edge
   is its budget guarantee and slightly better reader accuracy, not raw size.

**Recommendation:** until the reranker is retrained, use `optimize_context` without a
reranker, i.e. cosine ranking.

To improve the reranker:
- train it on far more varied labeled data;
- keep evaluating on held-out vaults like this one, never tuning on these questions;
- consider calibrating its scores before they feed relevance cutoffs.

## Limits

- 40 questions and 17 notes is small. One question is 2.5 percentage points.
- Questions and answers were written by the same author as the system, and answers are
  short facts copied from a single passage. Multi-passage reasoning isn't tested.
- The reader is a simple word-overlap extractor, not an LLM. "Reader correct" shows how
  context selection affects a weak reader. It does not measure LLM answer accuracy.
- Token counts are estimates, not a specific LLM tokenizer's counts.
- English only; macOS only.

## Reproducing

```sh
.venv/bin/python -m page_core.semantic prepare-model   # once
.venv/bin/python -m page_core.evaluation run           # writes benchmarks/results/
# Includes a check that the committed report reproduces exactly (except latency):
PAGE_TEST_SEMANTIC_MODEL=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest packages/core -q
```

Options: `--data`, `--model`, `--report`, `--summary`, `--budget` (default 300),
`--top-k` (default 5) and `--candidates` (default 10). The report also includes a
budget sweep (100, 300 and 1000 tokens) for both optimizer variants, and per-question
results.
