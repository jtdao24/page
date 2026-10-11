# Benchmark results

40 held-out questions over 17 notes. Budget 300 tokens for the Page optimizer, top 5 for embedding retrieval, 10 candidates per question. Tokens: `utf8-bytes/3`. Reader: `extractive-overlap-v1`.

| System | Avg input tokens | Token reduction vs full | Answer in context | Reader correct | Source precision |
|---|---|---|---|---|---|
| Full context (all notes) | 2606 | 0% | 100% | 62% | 6% |
| Embedding top-k | 199 | 92% | 100% | 72% | 64% |
| Page optimizer, cosine | 267 | 90% | 100% | 75% | 57% |
| Page optimizer, reranked | 43 | 98% | 72% | 68% | 92% |

| Retrieval order | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| Embedding | 0.775 | 1.000 | 1.000 | 1.000 | 0.875 |
| Reranked | 0.700 | 0.875 | 0.925 | 1.000 | 0.799 |

| Budget | System | Avg tokens | Answer in context | Reader correct |
|---|---|---|---|---|
| 100 | Page optimizer, cosine | 89 | 98% | 75% |
| 300 | Page optimizer, cosine | 267 | 100% | 75% |
| 1000 | Page optimizer, cosine | 306 | 100% | 75% |
| 100 | Page optimizer, reranked | 43 | 72% | 68% |
| 300 | Page optimizer, reranked | 43 | 72% | 68% |
| 1000 | Page optimizer, reranked | 43 | 72% | 68% |

Latency on the machine that produced this report (median ms per question): search 192.8, full_context 0.0, embedding_top_k 0.4, page_cosine 0.4, page_reranked 0.5.
