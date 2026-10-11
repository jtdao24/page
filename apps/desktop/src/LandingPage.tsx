import hacklantaLogo from "../hacklanta.png";
import { ScreenshotFolio } from "./landing/ScreenshotFolio";
import { CardMascot } from "./landing/CardMascot";
import { FeatureTour } from "./landing/FeatureTour";
import { PerformanceStats } from "./landing/PerformanceStats";


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
      <div className="nav-credit" aria-label=" For Hacklanta">
        <span>  for</span>
      <img src={hacklantaLogo} alt="Hacklanta" />
      </div>
      </a>
      <nav aria-label="Landing page navigation">
        <a className="landing-nav-link" href="#how-it-works">how it works</a><a className="landing-nav-link" href="#performance">performance</a>
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
        <a href="#how-it-works" className="landing-scroll"><span>THERE’S MORE TO THE STORY</span><span aria-hidden="true">↓</span></a>
      </section>

      <FeatureTour />

      <PerformanceStats />

      <section className="landing-download" id="download" aria-labelledby="download-title">
        <div className="download-heading"><p className="landing-kicker">YOUR NEXT IDEA NEEDS A PLACE TO START.</p><h2 id="download-title">turn a Page<span>.</span></h2></div>
        <div className="download-cards">
          <CardMascot />
          <div className="download-card"><span className="download-platform">PAGE / macOS</span><h3>your knowledge, ready to go.</h3><p>Apple Silicon · macOS 14 or later</p>
            {macDownloadUrl ? <>
              <a className="landing-primary" href={macDownloadUrl} download>Download for macOS <DownloadIcon /></a>
              <small>DMG installer · open it and drag Page to Applications.<br />Includes the local core and offline search model. No Python setup required.</small>
            </> : <>
              <button className="landing-primary" disabled>Coming soon</button>
              <p className="download-unavailable">We’re preparing a signed, Apple-notarized release. Follow the project on GitHub to hear when it’s out.</p>
            </>}
          </div>
        </div>
        <div className="download-footnote"><a href={REPOSITORY} target="_blank" rel="noreferrer">Follow Page on GitHub <Arrow diagonal /></a><a href={`${REPOSITORY}/blob/main/docs/development.md`} target="_blank" rel="noreferrer">Build it from source <Arrow diagonal /></a></div>
      </section>
    </main>

    <footer className="landing-footer"><a className="page-wordmark" href="#top">Page<span className="page-fold" aria-hidden="true" /></a><span>a personal space for a curious mind.</span>
      <nav aria-label="Footer navigation"><a href="#how-it-works">how it works</a><a href={REPOSITORY} target="_blank" rel="noreferrer">the project <Arrow diagonal /></a><a href="#top">back to top ↑</a></nav></footer>
  </div>;
}
