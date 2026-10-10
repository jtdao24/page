# Stage 9: neural context ranking

Page reorders Stage 8's retrieval candidates with a small learned model. It combines
the embedding similarity with lexical, passage-shape and knowledge-graph signals. This
stage builds and measures the ranker. It does not yet select context under a token
budget (Stage 10), run a broad benchmark (Stage 11) or call any LLM (Stage 12).

The code is `page_core.ranking`. It adds no dependencies: training uses the PyTorch
that Sentence Transformers already installs.

## How it works

1. **Candidates.** Stage 8's `SemanticIndex.search` returns passages ranked by cosine
   similarity from the pinned MiniLM model. That order is the baseline.
2. **Features.** `extract_features(query, hits, graph)` turns each candidate into 11
   numbers (`rank-features-v1`):

   | Feature | Meaning |
   |---|---|
   | `cosine` | Stage 8 similarity score |
   | `baseline_reciprocal_rank` | 1 / baseline position |
   | `gap_to_top` | Score minus the top candidate's score |
   | `query_terms_in_passage` | Share of query words (minus stopwords) in the passage |
   | `query_terms_in_path` | Share of query words in the note's folder and file name |
   | `is_heading` | The passage is a Markdown heading |
   | `length` | Passage length in tokens, log-scaled to 0–1 |
   | `is_first_passage` | The passage opens its note |
   | `backlinks` | How many other notes link to this note, log-scaled |
   | `links_top_note` | This note links to or from the top candidate's note |
   | `links_other_candidates` | Share of the other candidates' notes linked to this one |

   Graph features come from Stage 7's resolved wiki links. Features are pure Python and
   deterministic.
3. **Model.** The features are standardized and fed through a multilayer perceptron
   (11 inputs, 16 ReLU units, one output score). Candidates are reordered by that
   score; ties keep the baseline order.
4. **Training.** Listwise softmax loss over each query's candidates, so the model
   learns to put a relevant passage above the others for the same query. Adam with
   weight decay runs 400 full-batch epochs with a fixed seed, deterministic PyTorch
   algorithms and one CPU thread. The same data produces byte-identical weights.

## Checkpoints

A checkpoint is JSON: format, feature version and names, standardization, weights and
training settings. JSON is used instead of pickle, so loading a checkpoint can never
run code. `Reranker.load` rejects a checkpoint whose format, feature names or shapes
don't match, or whose values aren't finite numbers. Saving writes a temporary file and
renames it into place.

Inference (`Reranker.rerank`) is plain Python arithmetic on those weights and never
imports PyTorch. That keeps it fast for a model this size, and avoids the PyTorch and
FAISS OpenMP conflict described in [semantic-search.md](semantic-search.md).

## Data

`training/reranker/` holds a small labeled dataset:

- `vault/`: 11 Markdown notes on gardening, baking, databases, astronomy, testing and
  travel, with wiki links between some of them. It deliberately includes look-alike
  passages, such as compost versus kitchen scraps and database versus book indexes.
- `queries.jsonl`: 40 queries, 28 for training and 12 held out for testing. Each labels
  its relevant passage by note path and a text snippet, not by chunk ID, so labels
  survive chunking changes. Loading validates every line strictly.

Candidates are built by copying the fixture vault to a temporary folder, opening it
with `PersistentVault`, and searching it with the real model. The fixture is never
modified.

## Commands

```sh
# Train with the prepared model (see semantic-search.md); writes the checkpoint.
.venv/bin/python -m page_core.ranking train
# Evaluate on the held-out queries; writes benchmarks/reranker.json.
.venv/bin/python -m page_core.ranking evaluate
```

Options: `--data`, `--model`, `--report`, `--limit` (candidates per query, default 10)
and `--seed`.

## Results

Measured on the 12 held-out queries, with 10 candidates each
(`benchmarks/reranker.json`, macOS, October 10, 2026):

| Metric | Baseline (Stage 8) | Reranker (Stage 9) |
|---|---|---|
| Recall@1 | 0.833 | 0.917 |
| Recall@3 | 0.917 | 0.917 |
| Mean reciprocal rank | 0.889 | 0.938 |

The reranker moved two queries up and none down:
- "adding air to a compost heap" went from 2nd to 1st.
- "what to compost from baking day" went from 6th to 4th.

**What this does and does not show:**
- The dataset is tiny and hand-written by the same author as the model, and 12 test
  queries move by one query at a time. The improvement is a promising sign, not
  evidence of general gains.
- Nothing here measures LLM token usage or answer accuracy. Stage 11 owns a proper,
  larger evaluation against the full-context and embedding-only baselines.
- Retrieval quality is still capped by Stage 8: a passage outside the top 10 candidates
  can never be recovered by reranking.
- English-oriented, like the underlying embedding model.

## Validation

```sh
.venv/bin/python -m pytest packages/core -q
# Also checks that the committed checkpoint reproduces the committed report exactly.
PAGE_TEST_SEMANTIC_MODEL=1 HF_HUB_OFFLINE=1 .venv/bin/python -m pytest packages/core -q
```

The fast tests use a small offline keyword encoder and cover:
- features computed for crafted graphs;
- deterministic training that learns a planted signal;
- checkpoint round trips and nine kinds of tampering;
- pure-Python inference matching the PyTorch forward pass;
- reranking order, metric arithmetic and dataset integrity;
- the full pipeline on the fixture vault;
- importing `page_core.ranking` without loading PyTorch.
