import { lazy, Suspense } from "react";
import hacklantaLogo from "../hacklanta.png";
import { ScreenshotFolio } from "./landing/ScreenshotFolio";
import { PerformanceStats } from "./landing/PerformanceStats";


const LogoExperience = lazy(() => import("./landing/LogoExperience").then((module) => ({ default: module.LogoExperience })));


function Arrow({ diagonal = false }: { diagonal?: boolean }) {
  return <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d={diagonal ? "M6 18 18 6M6 6h12v12" : "M4 12h16m-6-6 6 6-6 6"} /></svg>;
}

function DownloadIcon() {
  return <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></svg>;
}

const REPOSITORY = "https://github.com/jtdao24/page";

export default function LandingPage({ macDownloadUrl }: { macDownloadUrl?: string }) {

  return <div className="page-landing" id="top">
    <a className="landing-skip" href="#landing-main">Skip to content</a>
    <header className="landing-nav">
      <a className="page-wordmark" href="#top" aria-label="Page home">Page<span className="page-fold" aria-hidden="true" />
      <div className="logo-experience-credit" aria-label=" For Hacklanta">
        <span>  for</span>
      <img src={hacklantaLogo} alt="Hacklanta" />
      </div>
      </a>
      <nav aria-label="Landing page navigation">
        <a className="landing-nav-link" href="#mission">the mission</a><a className="landing-nav-link" href="#how-it-works">how it works</a>
        <a className="landing-outline" href="#download">{macDownloadUrl ? <>Download <DownloadIcon /></> : "Coming soon"}</a>
      </nav>
    </header>

    <main id="landing-main">
      <section className="landing-hero" aria-labelledby="hero-title">
        <ScreenshotFolio />
        <div className="hero-copy"><p className="landing-kicker"><span />A LOCAL HOME FOR A CURIOUS MIND</p>
          <h1 id="hero-title"><span>your thoughts.</span><span>connected<span className="landing-period">.</span></span></h1>
          <p className="hero-description">Give your notes a little more room to think.<br />Keep notes, PDFs and web pages in one place,<br />and ask questions with answers that cite their sources.</p>
          <div className="hero-cta"><a className="landing-primary" href="#download">get on the same Page <Arrow /></a><p>Native macOS app. Your files stay on your Mac. No account needed.</p></div>
        </div>
        <a href="#mission" className="landing-scroll"><span>THERE’S MORE TO THE STORY</span><span aria-hidden="true">↓</span></a>
      </section>

      <div className="landing-belt" aria-label="Page principles"><span>plain Markdown</span><span aria-hidden="true">✳</span><span>your files, your control</span><span aria-hidden="true">✳</span><span>ideas in context</span><span aria-hidden="true">✳</span><span>local first</span></div>
      <Suspense fallback={<div className="logo-experience-placeholder" aria-hidden="true" />}>
        <LogoExperience />
      </Suspense>

      <section className="landing-section landing-mission" id="mission" aria-labelledby="mission-title">
        <div className="section-label"><span>01 / WHY WE MADE PAGE</span><span>KEEP THE KNOWLEDGE. FIND THE MEANING.</span></div>
        <div className="story-intro"><h2 id="mission-title">less lost.<br />more connected.</h2><div>
          <p className="mission-lead">We’re building Page to make personal knowledge easier to keep, connect, and put to work—without giving up ownership of your notes.</p>
          <p>We made it because useful ideas get scattered across documents, projects, and conversations. Saving them is only the beginning. The real value comes from returning to them when they matter.</p>
          <p>Page brings your Markdown files, PDFs and saved pages into a calm desktop workspace. When you ask a question, it finds the passages that matter and sends only those to the AI, and every answer shows where it came from. We measure how well that works, and publish the results below.</p>
        </div></div>
        <div className="mission-note"><span aria-hidden="true">✳</span><p>A home for your knowledge.<br /><strong>A starting point for what comes next.</strong></p><span className="mission-note-label">THE PAGE PROMISE<br />YOUR NOTES STAY YOURS.</span></div>
      </section>

      <section className="landing-section landing-how" id="how-it-works" aria-labelledby="how-title">
        <div className="section-label"><span>02 / HOW IT WORKS</span><span>ONE NOTE. A BIGGER PICTURE.</span></div>
        <div className="how-heading"><h2 id="how-title">a little context.<br />a lot to come back to.</h2><p>Start with files you own.<br />Build a workspace that grows with you.</p></div>
        <ol className="landing-steps">
          <li><span className="step-number">01 / COLLECT</span><h3>bring everything in.</h3><p>Write Markdown notes, drop PDFs and code into your vault folder, or save a web page as a note. Your files stay plain, local, and yours.</p></li>
          <li><span className="step-number">02 / CONNECT</span><h3>see the big picture.</h3><p>Link ideas with [[wiki links]] and explore them in an interactive graph. Search finds passages by meaning, not just matching words, entirely on your Mac.</p></li>
          <li><span className="step-number">03 / ASK</span><h3>get answers with sources.</h3><p>Ask a question and Page sends the AI only the passages that matter. Every answer cites the exact notes and lines it used, and tools like Claude Code can use the same context through MCP.</p></li>
        </ol>
      </section>



      <PerformanceStats />

      <section className="landing-download" id="download" aria-labelledby="download-title">
        <div className="download-heading"><p className="landing-kicker">YOUR NEXT IDEA NEEDS A PLACE TO START.</p><h2 id="download-title">turn a Page<span>.</span></h2><p>A little space for everything you know.<br />And everything you’re still figuring out.</p></div>
        <div className="download-cards">
          <div className="download-card"><span className="download-platform">PAGE / macOS</span><h3>your knowledge, ready to go.</h3><p>Apple Silicon · macOS 14 or later</p>
            {macDownloadUrl ? <>
              <a className="landing-primary" href={macDownloadUrl} download>Download for macOS <DownloadIcon /></a>
              <small>DMG installer · open it and drag Page to Applications.<br />Includes the local core and offline search model. No Python setup required.</small>
            </> : <>
              <button className="landing-primary" disabled>Coming soon</button>
              <p className="download-unavailable">We’re preparing a signed, Apple-notarized release. Follow the project on GitHub to hear when it’s out.</p>
              <small>It will include everything it needs: the local core and offline search model, with no Python setup.</small>
            </>}
          </div>
        </div>
        <div className="download-footnote"><a href={REPOSITORY} target="_blank" rel="noreferrer">Follow Page on GitHub <Arrow diagonal /></a><a href={`${REPOSITORY}/blob/main/docs/development.md`} target="_blank" rel="noreferrer">Build it from source <Arrow diagonal /></a></div>
      </section>
    </main>

    <footer className="landing-footer"><a className="page-wordmark" href="#top">Page<span className="page-fold" aria-hidden="true" /></a><span>a personal space for a curious mind.</span>
      <nav aria-label="Footer navigation"><a href="#mission">the mission</a><a href={REPOSITORY} target="_blank" rel="noreferrer">the project <Arrow diagonal /></a><a href="#top">back to top ↑</a></nav></footer>
  </div>;
}
