import { useEffect, useRef, useState } from "react";
import pageIcon from "../assets/page-icon.png";
import { Icon, type IconName } from "./Icon";

const STEPS: { icon: IconName | "page"; title: string; text: string }[] = [
  { icon: "page", title: "Welcome to Page", text: "A quiet place to write and keep what you know. Here's a quick look at what it can do." },
  { icon: "note", title: "Your notes are just files", text: "Every note is a Markdown file in a folder you choose. No account, no lock-in. Link notes by typing [[ and a name." },
  { icon: "graph", title: "Find and connect", text: "Search finds passages by meaning, not just exact words. The graph shows how your notes link together." },
  { icon: "ask", title: "Ask your notes", text: "Press ⌘K and ask a question. Page picks the relevant passages, and the answer cites exactly where it came from." },
  { icon: "pdf", title: "Bring everything in", text: "Drop PDFs, code and text files into your vault, or save a web page. They become searchable too." },
];

export const INTRO_SEEN_KEY = "page.intro.seen.v1";

/** A short, skippable tour shown on first launch and from the home screen. */
export function Intro({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  const next = useRef<HTMLButtonElement>(null);
  const last = step === STEPS.length - 1;
  const go = (target: number) => {
    setDirection(target > step ? "forward" : "back");
    setStep(Math.max(0, Math.min(STEPS.length - 1, target)));
  };
  useEffect(() => { next.current?.focus(); }, []);
  const current = STEPS[step];

  return <div className="intro-backdrop" role="dialog" aria-modal="true" aria-label="Introduction to Page"
    onKeyDown={(event) => {
      if (event.key === "Escape") onDone();
      if (event.key === "ArrowRight") { event.preventDefault(); if (last) onDone(); else go(step + 1); }
      if (event.key === "ArrowLeft") { event.preventDefault(); go(step - 1); }
    }}>
    <div className="intro-panel">
      <button className="intro-skip" onClick={onDone}>Skip</button>
      <div key={step} className={`intro-slide is-${direction}`}>
        <div className="intro-art">
          {current.icon === "page" ? <img src={pageIcon} alt="" width={96} height={96} /> : <Icon name={current.icon} size={40} />}
        </div>
        <h2>{current.title}</h2>
        <p>{current.text}</p>
      </div>
      <div className="intro-dots" role="tablist" aria-label="Tour steps">
        {STEPS.map((item, index) => <button key={item.title} role="tab" aria-selected={index === step}
          aria-label={`Step ${index + 1}: ${item.title}`} className={index === step ? "is-active" : ""} onClick={() => go(index)} />)}
      </div>
      <div className="intro-actions">
        <button className="intro-back" disabled={step === 0} onClick={() => go(step - 1)}>Back</button>
        <button ref={next} className="intro-next" onClick={() => (last ? onDone() : go(step + 1))}>{last ? "Get started" : "Next"}</button>
      </div>
    </div>
  </div>;
}
