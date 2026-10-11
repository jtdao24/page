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

export default function LandingPage({ appHref = "/", macDownloadUrl }: {
  appHref?: string; macDownloadUrl?: string;
}) {

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
        <a className="landing-outline" href="#download">Download <DownloadIcon /></a>
      </nav>
    </header>

    <main id="landing-main">
      <section className="landing-hero" aria-labelledby="hero-title">
        <ScreenshotFolio />
        <div className="hero-copy"><p className="landing-kicker"><span />A LOCAL HOME FOR A CURIOUS MIND</p>
          <h1 id="hero-title"><span>your thoughts.</span><span>connected<span className="landing-period">.</span></span></h1>
          <p className="hero-description">Give your notes a little more room to think.<br />A Markdown workspace for keeping ideas,<br />seeing connections, and finding your way back.</p>
          <div className="hero-cta"><a className="landing-primary" href="#download">get on the same Page <Arrow /></a><p>Native desktop app. Local files. No account needed to explore.</p></div>
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
          <p>Page brings your Markdown files into a calm desktop workspace. Our longer-term mission is to help AI use the context a question needs, with clear sources and less unnecessary input. That’s a goal we’re building toward and measuring.</p>
        </div></div>
        <div className="mission-note"><span aria-hidden="true">✳</span><p>A home for your knowledge.<br /><strong>A starting point for what comes next.</strong></p><span className="mission-note-label">THE PAGE PROMISE<br />YOUR NOTES STAY YOURS.</span></div>
      </section>

      <section className="landing-section landing-how" id="how-it-works" aria-labelledby="how-title">
        <div className="section-label"><span>02 / HOW IT WORKS</span><span>ONE NOTE. A BIGGER PICTURE.</span></div>
        <div className="how-heading"><h2 id="how-title">a little context.<br />a lot to come back to.</h2><p>Start with files you own.<br />Build a workspace that grows with you.</p></div>
        <ol className="landing-steps">
          <li><span className="step-number">01 / COLLECT</span><h3>bring your notes.</h3><p>Open a local Markdown vault in Page. Read, write, and organize your files with the installed local core. Your original notes remain the source of truth.</p></li>
          <li><span className="step-number">02 / CONNECT</span><h3>see the big picture.</h3><p>The desktop gives you a focused Markdown editor and folder navigation. Try the experimental graph preview to explore entries in tabs and read ideas side by side.</p></li>
          <li><span className="step-number">03 / RETURN</span><h3>pick up the thread.</h3><p>Read the full note and see where it came from. Local semantic indexing lays the groundwork for finding relevant context beyond exact keywords.</p></li>
        </ol>
      </section>



      <PerformanceStats />

      <section className="landing-download" id="download" aria-labelledby="download-title">
        <div className="download-heading"><p className="landing-kicker">YOUR NEXT IDEA NEEDS A PLACE TO START.</p><h2 id="download-title">turn a Page<span>.</span></h2><p>A little space for everything you know.<br />And everything you’re still figuring out.</p></div>
        <div className="download-cards">
          <div className="download-card"><span className="download-platform">PAGE / macOS</span><h3>your knowledge, ready to go.</h3><p>Apple Silicon · macOS 14 or later</p>
            {macDownloadUrl ? <a className="landing-primary" href={macDownloadUrl} download>Download for macOS <DownloadIcon /></a> : <><button className="landing-primary" disabled>Download being prepared <DownloadIcon /></button><p className="download-unavailable">A download will appear when a build is published.</p></>}
            <small>DMG installer · open it and drag Page to Applications.<br />Includes the local core and offline search model. No Python setup required.<br />Locally signed; not Apple-notarized.</small>
          </div>
        </div>
        <div className="download-footnote"><a href={appHref}>Just looking? Open the workspace preview <Arrow diagonal /></a><a href="https://github.com/jtdao24/page/blob/main/docs/packaging.md" target="_blank" rel="noreferrer">Installation & source <Arrow diagonal /></a></div>
      </section>
    </main>

    <footer className="landing-footer"><a className="page-wordmark" href="#top">Page<span className="page-fold" aria-hidden="true" /></a><span>a personal space for a curious mind.</span>
      <nav aria-label="Footer navigation"><a href="#mission">the mission</a><a href="https://github.com/jtdao24/page" target="_blank" rel="noreferrer">the project <Arrow diagonal /></a><a href="#top">back to top ↑</a></nav></footer>
  </div>;
}
