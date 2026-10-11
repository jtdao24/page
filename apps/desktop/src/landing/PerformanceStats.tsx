import benchmark from "../../../../benchmarks/results/landing-performance.json";

const reportUrl = new URL("../../../../benchmarks/results/landing-performance.json", import.meta.url).href;
const baseline = benchmark.systems.full_context;
const production = benchmark.systems.page_cosine;
const experimental = benchmark.systems.page_reranked;
const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
const tokens = (value: number) => Math.round(value).toLocaleString("en-US");

export function PerformanceStats() {
  return <section className="landing-section landing-performance" id="performance" aria-labelledby="performance-title">
    <div className="section-label"><span>PERFORMANCE, MEASURED</span><span>LESS CONTEXT. CLEAR SOURCES.</span></div>
    <div className="performance-heading"><h2 id="performance-title">a lighter load.<br />a clearer answer.</h2>
      <p>Compared with sending every note in our benchmark vault.</p></div>
    <dl className="performance-stats">
      <div><dt>Less context sent</dt><dd>{percent(production.token_reduction_vs_full)}</dd>
        <p>{tokens(baseline.avg_tokens)} → {tokens(production.avg_tokens)} tokens on average.</p></div>
      <div><dt>Answer coverage</dt><dd>{Math.round(production.answer_support * 100)}%</dd>
        <p>The answer stayed in context for all {benchmark.dataset.questions} questions.</p></div>
      <div><dt>Median local search</dt><dd>{Math.round(benchmark.latency_ms.search.median)}<span>ms</span></dd>
        <p>Finding the passages, on a Mac.</p></div>
    </dl>
    <details className="performance-method">
      <summary>How we measured</summary>
      <p>Measured October 10, 2026: {benchmark.dataset.questions} held-out questions across {benchmark.dataset.notes} notes, using local MiniLM retrieval and the production cosine optimizer with a {benchmark.settings.budget}-token context budget. The baseline sends all notes. Tokens use a UTF-8 byte estimate, not Gemini’s billing tokenizer; prompts and output tokens are excluded. Answer coverage checks whether the expected answer is present, not whether an AI answer is correct. Search time is the median with the model loaded, excluding model startup and Gemini’s response.</p>
      <p>The experimental neural reranker saved {percent(experimental.token_reduction_vs_full)} of context tokens, but retained expected answers in only {percent(experimental.answer_support)} of questions. It isn’t the production default. Results on this small fixture don’t guarantee the same savings for every vault.</p>
      <a className="landing-text-link" href={reportUrl} download="page-context-benchmark.json">Download the benchmark results <span aria-hidden="true">↗</span></a>
    </details>
  </section>;
}
