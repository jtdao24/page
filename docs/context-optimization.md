# Stage 10: context optimization

`page_core.context.optimize_context` turns ranked search candidates into a compact,
source-attributed context package that never exceeds a token budget. It is the piece
that is meant to save LLM tokens. Stage 11 measures how well it does that; Stage 12
sends the package to a model.

It is pure Python: no I/O, model calls or PyTorch import, and the same inputs always
give the same package.

## Using it

```python
from page_core.context import optimize_context

package = optimize_context(query, hits, graph, budget=500, reranker=reranker)
package.result.context_text      # what to send to the model
package.result.selected_chunks   # exact source spans used
package.blocks                   # one entry per source block, with path and lines
package.usage                    # token and selection accounting
```

- `hits`: Stage 8 `SemanticIndex.search` results, in their original order.
- `graph`: the Stage 7 `build_graph` snapshot for the same notes.
- `reranker`: optional Stage 9 model. Without it, cosine similarity ranks candidates.
- `budget`: the maximum number of tokens for the whole package.

## How passages are chosen

1. **Relevance.** Each candidate gets a relevance relative to the best one, which
   scores 1.0. With a reranker that is `exp(score - top score)`, since Stage 9 scores
   have no fixed range; otherwise `cosine / top cosine`. Candidates below
   `min_relevance` (default 0.25) are dropped, which is often where most savings come
   from.
2. **Greedy selection** (maximal marginal relevance). The next passage is the one with
   the highest:
   - `0.7 × relevance`
   - minus `0.3 ×` its word overlap with passages already chosen (`diversity`);
   - plus `0.2 ×` the share of query words it covers that nothing chosen covers yet
     (`coverage_weight`);
   - plus `0.1` if its note links to or from a note already chosen (`graph_weight`,
     from Stage 7 wiki links).
3. **Redundancy.** Exact duplicates (ignoring whitespace) and near-duplicates (word-set
   similarity of 0.8 or more, `redundancy_threshold`) of chosen passages are skipped.
4. **Budget.** A passage is added only if the whole package, including the new block
   and its source line, still fits. At most `max_passages` (default 8) are used.
5. **Excerpts.** If a passage doesn't fit, it is cut down to its sentences that mention
   query words, in source order, keeping as many as fit. Each kept sentence becomes a
   `Chunk` whose bytes are an exact slice of the note, so nothing is paraphrased or
   generated. If no sentence helps or fits, the passage is dropped.

## Output format

```text
[1] garden/compost.md (lines 5-6)
Turn the pile every week to add air. A pile that smells of ammonia has too much green material; add more dry leaves.

[2] databases/transactions.md (line 5, excerpt)
Isolation levels control what concurrent transactions can see.
```

Line numbers describe the text shown, so surrounding blank lines are excluded.
Excerpt sentences are joined with ` … `.

`package.usage` reports:
- the counter name, budget and tokens used;
- `candidate_tokens`: what including all candidates whole would have cost;
- how many candidates were considered, selected and compressed;
- how many were dropped as redundant, for budget, for low relevance, or because of
  the passage limit. These always add up to the number considered.

## Token counting

Counting goes through a `TokenCounter` protocol (`name` and `count(text)`), and the
budget is always checked against the complete assembled text. The default
`Utf8TokenEstimate` counts one token per three UTF-8 bytes, rounded up. Common LLM
tokenizers average about four characters per English token, so this overestimates on
purpose and keeps packages within real limits. Page doesn't depend on a particular LLM
provider; once Stage 12 chooses a model, its exact tokenizer can be passed as
`counter`.

## Early measurements

On the Stage 9 fixture (40 queries, 10 candidates each, real MiniLM model, macOS,
October 10, 2026). "Found" means a labeled passage, or part of it, made it into the
package:

| Budget | Ranking | Found | Avg tokens | Saved vs. all candidates |
|---|---|---|---|---|
| 60 | Stage 8 cosine | 35/40 | 53 | 88% |
| 60 | Stage 9 reranker | 37/40 | 46 | 90% |
| 120 | Stage 8 cosine | 38/40 | 111 | 75% |
| 120 | Stage 9 reranker | 39/40 | 53 | 88% |
| 250 | Stage 8 cosine | 39/40 | 226 | 50% |
| 250 | Stage 9 reranker | 39/40 | 54 | 88% |

With the reranker, packages stay small even when the budget grows, because its scores
separate the best passage more sharply and the relevance cutoff removes the rest.

**Limits of these numbers:**
- 28 of the 40 queries trained the reranker, which flatters it.
- The fixture is tiny and hand-written.
- "Found" checks retrieval, not whether an LLM answers correctly.

Stage 11 owns the rigorous comparison against full-context and embedding-only
baselines, including answer accuracy.

## Held-out results (Stage 11)

On the separate Stage 11 evaluation vault:
- **With cosine ranking,** the optimizer used 90% fewer tokens than sending every
  note, and still contained the answer for all 40 questions.
- **With the Stage 9 reranker,** it kept too little: the answer was missing for 28% of
  questions.

Use `optimize_context` without a reranker until the reranker is retrained. See
[evaluation](evaluation.md).

## Validation

```sh
.venv/bin/python -m pytest packages/core/tests/test_context.py -q
```

The tests cover:
- the budget across a hundred budgets, the empty package, relevance and passage
  limits;
- exact and near-duplicate removal, preferring complementary passages, and graph
  credit deciding between equal passages;
- exact-byte excerpts and dropping what cannot fit, source lines, and reranker order;
- determinism, custom counters, and input validation;
- the whole fixture vault, and importing without PyTorch.
