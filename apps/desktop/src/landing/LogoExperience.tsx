import { useEffect, useState } from "react";
import appIcon from "../../app-icon.png";
import hacklantaLogo from "../../hacklanta.png";
import { LogoScene, type LogoSceneHandles } from "./LogoScene";
import { useLogoScrollTimeline } from "./useLogoScrollTimeline";

const features = [
  { title: "Markdown Vault", text: "Your plain Markdown files remain the source of truth." },
  { title: "Knowledge Graph", text: "Links and relationships reveal the shape of what you know." },
  { title: "Semantic Search", text: "Find relevant passages by meaning, not only exact words." },
  { title: "Neural Context Engine", text: "Rank and filter passages against the question at hand." },
  { title: "Optimized AI Context", text: "Assemble the smallest useful context with clear sources." },
];

function supportsWebGL() {
  if (typeof document === "undefined") return false;
  if (typeof navigator !== "undefined" && /jsdom/i.test(navigator.userAgent)) return false;
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

function ReducedMotionSequence() {
  return <ol className="logo-experience-reduced-list">
    {features.map((feature, index) => <li key={feature.title}>
      <span>0{index + 1}</span><div><h3>{feature.title}</h3><p>{feature.text}</p></div>
    </li>)}
  </ol>;
}

export function LogoExperience() {
  const [section, setSection] = useState<HTMLElement | null>(null);
  const [handles, setHandles] = useState<LogoSceneHandles | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [webGL] = useState(supportsWebGL);
  const [mobile, setMobile] = useState(false);

  useEffect(() => {
    const query = typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)")
      : null;
    if (!query) return;
    const update = () => setReducedMotion(query.matches);
    update();
    query.addEventListener("change", update);
    const viewport = window.matchMedia("(max-width: 800px)");
    const updateViewport = () => setMobile(viewport.matches);
    updateViewport();
    viewport.addEventListener("change", updateViewport);
    return () => {
      query.removeEventListener("change", update);
      viewport.removeEventListener("change", updateViewport);
    };
  }, []);

  useLogoScrollTimeline(section, handles, reducedMotion);

  return <section ref={setSection} className={`logo-experience${reducedMotion ? " is-reduced-motion" : ""}`} aria-labelledby="logo-experience-title">
    <div className="logo-experience-sticky">
      <div className="logo-experience-heading">
        <p className="landing-kicker"><span />FROM PERSONAL KNOWLEDGE TO USEFUL CONTEXT</p>
        <h2 id="logo-experience-title">five layers.<br /><em>one clearer Page.</em></h2>
        <div className="logo-experience-credit" aria-label="For Hacklanta">
          <span>for</span>
          <img src={hacklantaLogo} alt="Hacklanta" />
        </div>
      </div>
      {webGL && !reducedMotion ? <LogoScene onReady={setHandles} lowComplexity={mobile} /> : <div className="logo-experience-static-mark" aria-hidden="true"><img src={appIcon} alt="" /></div>}
      <div className="logo-experience-features">
        {features.map((feature, index) => <article key={feature.title} className={`logo-experience-feature logo-experience-feature--${index}`} data-layer={index}>
          <span>0{index + 1} / LAYER</span><h3>{feature.title}</h3><p>{feature.text}</p>
        </article>)}
      </div>
      {(!webGL || reducedMotion) && <div className="logo-experience-fallback-copy">
        <p>{webGL ? "Motion is reduced, so the architecture is shown as a readable sequence." : "Your browser cannot display the 3D scene, so the architecture is shown as a readable sequence."}</p>
        <ReducedMotionSequence />
      </div>}
      <div className="logo-experience-scroll-note">SCROLL TO MOVE THROUGH THE LAYERS <span aria-hidden="true">↓</span></div>
    </div>
  </section>;
}
