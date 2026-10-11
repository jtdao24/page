import { useEffect, useRef, useState } from "react";
import write from "../assets/layers/write.png";
import graph from "../assets/layers/graph.png";
import search from "../assets/layers/search.png";
import ask from "../assets/layers/ask.png";

const STEPS = [
  { label: "01 / WRITE", title: "plain notes you own.", text: "Markdown files in a folder on your Mac. Link ideas with [[double brackets]], and drop in PDFs and code too.",
    image: write, alt: "Page editing a Markdown note, with the vault's files in the sidebar" },
  { label: "02 / CONNECT", title: "see how ideas link up.", text: "Every note and link in one interactive graph, right beside the note you're reading.",
    image: graph, alt: "Page's knowledge graph open beside a note, showing its links and backlinks" },
  { label: "03 / SEARCH", title: "find things by meaning.", text: "Search runs on your Mac and reads inside PDFs, so the right passage turns up even when the words don't match.",
    image: search, alt: "Search results in Page, with a PDF passage ranked first" },
  { label: "04 / ASK", title: "answers with sources.", text: "Page sends the AI only the passages that matter. Every answer cites them, and shows how much it saved.",
    image: ask, alt: "A cited answer in Page's ask card, with the token savings shown at the top" },
] as const;

/** Four short steps; on wide screens a pinned screenshot changes as each step scrolls into view. */
export function FeatureTour() {
  const [active, setActive] = useState(0);
  const steps = useRef<(HTMLLIElement | null)[]>([]);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) setActive(Number((entry.target as HTMLElement).dataset.step));
      }
    }, { rootMargin: "-45% 0px -45% 0px" });
    for (const step of steps.current) if (step) observer.observe(step);
    return () => observer.disconnect();
  }, []);

  return <section className="landing-section landing-tour" id="how-it-works" aria-labelledby="tour-title">
    <div className="section-label"><span>HOW IT WORKS</span><span>ONE FOLDER. FOUR WAYS IN.</span></div>
    <h2 id="tour-title" className="tour-title">a little context.<br />a lot to come back to.</h2>
    <div className="tour-layout">
      <ol className="tour-steps">
        {STEPS.map((step, index) => <li key={step.label} data-step={index} className={index === active ? "is-active" : undefined}
          ref={(element) => { steps.current[index] = element; }}>
          <span className="step-number">{step.label}</span><h3>{step.title}</h3><p>{step.text}</p>
          <img className="tour-inline-shot" src={step.image} alt={step.alt} loading="lazy" width={1600} height={1013} />
        </li>)}
      </ol>
      <div className="tour-frame" aria-hidden="true">
        {STEPS.map((step, index) => <img key={step.label} src={step.image} alt="" loading="lazy" width={1600} height={1013}
          className={index === active ? "is-active" : undefined} />)}
      </div>
    </div>
  </section>;
}
