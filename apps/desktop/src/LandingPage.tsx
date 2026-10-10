import { useState } from "react";
import heroImage from "./assets/page-books.png";

const examples = [
  { title: "The art of noticing", category: "IDEAS", text: "Good ideas begin with small observations. Keep the sentences, questions, and patterns that catch your attention.", path: "Ideas/the-art-of-noticing.md", x: 24, y: 35 },
  { title: "Things I want to build", category: "PROJECTS", text: "An idea doesn’t have to be finished to deserve a home. Collect the sketches, experiments, and what-ifs along the way.", path: "Projects/things-i-want-to-build.md", x: 69, y: 24 },
  { title: "Notes from the margins", category: "READING", text: "The parts worth returning to, and the thoughts they leave behind. A personal collection of things that made you think.", path: "Reading/notes-from-the-margins.md", x: 56, y: 73 },
];

function Arrow({ diagonal = false }: { diagonal?: boolean }) {
  return <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d={diagonal ? "M6 18 18 6M6 6h12v12" : "M4 12h16m-6-6 6 6-6 6"} /></svg>;
}

function DownloadIcon() {
  return <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></svg>;
}

export default function LandingPage({ appHref = "/", macDownloadUrl, windowsDownloadUrl }: {
  appHref?: string; macDownloadUrl?: string; windowsDownloadUrl?: string;
}) {
  const [selected, setSelected] = useState(0);
  const example = examples[selected];

  return <div className="page-landing" id="top">
    <a className="landing-skip" href="#landing-main">Skip to content</a>
    <header className="landing-nav">
      <a className="page-wordmark" href="#top" aria-label="Page home">Page<span className="page-fold" aria-hidden="true" /></a>
      <nav aria-label="Landing page navigation">
        <a className="landing-nav-link" href="#mission">the mission</a><a className="landing-nav-link" href="#how-it-works">how it works</a>
        <a className="landing-auth-link" href="/login/">Log In</a><a className="landing-auth-link landing-signup" href="/signup/">Sign Up</a>
        <a className="landing-open" href={appHref}>Open App <Arrow diagonal /></a>
        <a className="landing-outline" href="#download">Download <DownloadIcon /></a>
      </nav>
    </header>

    <main id="landing-main">
      <section className="landing-hero" aria-labelledby="hero-title">
        <div className="landing-art"><img src={heroImage} alt="Clothbound books, an open book, and loose pages taking flight" width="1254" height="1254" fetchPriority="high" />
          <span className="art-caption">good thoughts deserve a place to land.</span></div>
        <div className="hero-copy"><p className="landing-kicker"><span />A LOCAL HOME FOR A CURIOUS MIND</p>
          <h1 id="hero-title"><span>your thoughts.</span><span>connected<span className="landing-period">.</span></span></h1>
          <p className="hero-description">Give your notes a little more room to think.<br />A Markdown workspace for keeping ideas,<br />seeing connections, and finding your way back.</p>
          <div className="hero-cta"><a className="landing-primary" href="#download">get on the same Page <Arrow /></a><p>Native desktop app. Local files. No account needed to explore.</p></div>
        </div>
        <a href="#mission" className="landing-scroll"><span>THERE’S MORE TO THE STORY</span><span aria-hidden="true">↓</span></a>
      </section>

      <div className="landing-belt" aria-label="Page principles"><span>plain Markdown</span><span aria-hidden="true">✳</span><span>your files, your control</span><span aria-hidden="true">✳</span><span>ideas in context</span><span aria-hidden="true">✳</span><span>local first</span></div>

      <section className="landing-section landing-mission" id="mission" aria-labelledby="mission-title">
        <div className="section-label"><span>01 / WHY WE MADE PAGE</span><span>KEEP THE KNOWLEDGE. FIND THE MEANING.</span></div>
        <div className="story-intro"><h2 id="mission-title">less lost.<br />more connected.</h2><div>
          <p className="mission-lead">We’re building Page to make personal knowledge easier to keep, connect, and put to work—without giving up ownership of your notes.</p>
          <p>We made it because useful ideas get scattered across documents, projects, and conversations. Saving them is only the beginning. The real value comes from returning to them when they matter.</p>
          <p>Page brings your Markdown files into a calm desktop workspace. Our longer-term mission is to help AI use the context a question needs, with clear sources and less unnecessary input. That’s a goal we’re building toward and measuring.</p>
        </div></div>
        <div className="mission-note"><span aria-hidden="true">✳</span><p>A home for your knowledge.<br /><strong>A starting point for what comes next.</strong></p><span className="mission-note-label">THE PAGE PROMISE<br />YOUR NOTES STAY YOURS.</span></div>
      </section>

      <section className="landing-section landing-how" id="how-it-works" aria-labelledby="how-title">
        <div className="section-label"><span>02 / HOW IT WORKS</span><span>ONE NOTE. A BIGGER PICTURE.</span></div>
        <div className="how-heading"><h2 id="how-title">a little context.<br />a lot to come back to.</h2><p>Start with files you own.<br />Build a workspace that grows with you.</p></div>
        <ol className="landing-steps">
          <li><span className="step-number">01 / COLLECT</span><h3>bring your notes.</h3><p>Keep your writing in a local Markdown vault. Connect it to Page’s local core and index the files. Your original notes remain the source of truth.</p></li>
          <li><span className="step-number">02 / CONNECT</span><h3>see the big picture.</h3><p>Explore entries as nodes in your graph. Browse one folder at a time, open a note in a tab, or split the workspace to read ideas side by side.</p></li>
          <li><span className="step-number">03 / RETURN</span><h3>pick up the thread.</h3><p>Read the full note and see where it came from. Local semantic indexing lays the groundwork for finding relevant context beyond exact keywords.</p></li>
        </ol>
      </section>

      <section className="landing-section landing-library" id="the-library" aria-labelledby="library-title">
        <div className="section-label"><span>03 / A LOOK INSIDE</span><span>YOUR KNOWLEDGE, IN GOOD COMPANY.</span></div>
        <div className="library-demo-layout"><div className="library-demo-copy"><h2 id="library-title">follow<br />a thought.</h2><p>Every node is an entry. Open it, read it, and make room beside it for another idea.</p>
          <a className="landing-text-link" href={appHref}>explore the workspace preview <Arrow diagonal /></a><p className="demo-disclaimer">Illustrative sample below. Graph lines in the app currently show shared collections.</p></div>
          <div className="landing-demo"><div className="demo-topbar"><span className="demo-brand">Page</span><span className="demo-label">ILLUSTRATIVE PREVIEW</span><span className="demo-dots" aria-hidden="true">● ● ●</span></div>
            <div className="demo-tabs"><span>Your graph</span><span className="demo-active-tab">{example.title}</span></div>
            <div className="demo-main"><div className="demo-graph" role="group" aria-label="Sample knowledge graph">
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d="M24 35 69 24 56 73Z" /><path d="M24 35 9 69M69 24 88 53M56 73 83 89" /></svg>
              <span className="demo-satellite satellite-one" aria-hidden="true" /><span className="demo-satellite satellite-two" aria-hidden="true" /><span className="demo-satellite satellite-three" aria-hidden="true" />
              {examples.map((note, index) => <button key={note.title} className={`demo-node${selected === index ? " is-selected" : ""}`} style={{ left: `${note.x}%`, top: `${note.y}%` }} onClick={() => setSelected(index)} aria-pressed={selected === index} aria-label={`Read sample: ${note.title}`}><span className="demo-node-dot" /><span className="demo-node-label">{note.title}</span></button>)}
            </div>
              <div className="demo-reading" aria-live="polite"><span>{example.category} / OPEN NOTE</span><h3>{example.title}</h3><p>{example.text}</p><small>{example.path}</small></div>
              <p className="demo-instruction">Choose a node. There’s a thought inside.</p>
            </div>
          </div>
        </div>
      </section>

      <section className="landing-section landing-questions" aria-labelledby="questions-title"><div className="section-label"><span>04 / A FEW GOOD QUESTIONS</span><span>BEFORE YOU TURN THE PAGE.</span></div>
        <div className="questions-layout"><h2 id="questions-title">good to<br />know.</h2><div className="landing-faq">
          <details><summary>Where do my notes live?<span aria-hidden="true">+</span></summary><p>In your own Markdown vault on your device. Page builds a local index around your files; your Markdown remains the source of truth.</p></details>
          <details><summary>Do I need an account?<span aria-hidden="true">+</span></summary><p>No account is required for the local workspace. Online sign-in is not configured yet. Future accounts will support connected services and synchronization.</p></details>
          <details><summary>Can I ask AI about my notes?<span aria-hidden="true">+</span></summary><p>Not yet. The question box currently keeps an unsent local draft. AI answers, neural context ranking, and token-budget controls are planned. Local semantic indexing and a development search API already exist.</p></details>
          <details><summary>What’s included in the download?<span aria-hidden="true">+</span></summary><p>The current macOS development download contains the native Page desktop app, including the sample workspace. To read and index your own vault, the Python core must be installed and started separately. This is not yet a self-contained release.</p></details>
          <details><summary>Will Page be available on Windows?<span aria-hidden="true">+</span></summary><p>Windows is a planned platform. A Windows download is not available yet, and local metadata permissions still need platform-specific support.</p></details>
        </div></div>
      </section>

      <section className="landing-download" id="download" aria-labelledby="download-title">
        <div className="download-heading"><p className="landing-kicker">YOUR NEXT IDEA NEEDS A PLACE TO START.</p><h2 id="download-title">turn a Page<span>.</span></h2><p>A little space for everything you know.<br />And everything you’re still figuring out.</p></div>
        <div className="download-cards">
          <div className="download-card"><span className="download-platform">01 / macOS</span><h3>make yourself at home.</h3><p>Apple Silicon · development build</p>
            {macDownloadUrl ? <a className="landing-primary" href={macDownloadUrl} download>Download for macOS <DownloadIcon /></a> : <><button className="landing-primary" disabled>Download being prepared <DownloadIcon /></button><p className="download-unavailable">A download will appear when a build is published.</p></>}
            <small>Native desktop app. The local core is installed separately.<br />This development build is not notarized.</small>
          </div>
          <div className="download-card download-card--secondary"><span className="download-platform">02 / WINDOWS</span><h3>another chapter, soon.</h3><p>Windows support is in progress.</p>
            {windowsDownloadUrl ? <a className="landing-outline" href={windowsDownloadUrl} download>Download for Windows <DownloadIcon /></a> : <button className="landing-outline" disabled>Windows coming soon</button>}
            <small>We’ll add a download when a Windows build is ready.</small>
          </div>
        </div>
        <div className="download-footnote"><a href={appHref}>Just looking? Open the workspace preview <Arrow diagonal /></a><a href="https://github.com/jtdao24/page/blob/caiden/docs/ingestion.md#install-and-run" target="_blank" rel="noreferrer">Local core setup & source <Arrow diagonal /></a></div>
      </section>
    </main>

    <footer className="landing-footer"><a className="page-wordmark" href="#top">Page<span className="page-fold" aria-hidden="true" /></a><span>a personal space for a curious mind.</span>
      <nav aria-label="Footer navigation"><a href="#mission">the mission</a><a href="https://github.com/jtdao24/page" target="_blank" rel="noreferrer">the project <Arrow diagonal /></a><a href="#top">back to top ↑</a></nav></footer>
  </div>;
}
