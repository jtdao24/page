import { useState } from "react";
import heroImage from "./assets/page-books.png";

const examples = [
  { title: "The art of noticing", category: "IDEAS", color: "green", text: "Good ideas begin with small observations. Keep the sentences, questions, and patterns that catch your attention.", path: "ideas / the-art-of-noticing.md" },
  { title: "Things I want to build", category: "PROJECTS", color: "orange", text: "An idea doesn’t have to be finished to deserve a home. Collect the sketches, experiments, and what-ifs along the way.", path: "projects / things-i-want-to-build.md" },
  { title: "Notes from the margins", category: "READING", color: "stone", text: "The parts worth returning to, and the thoughts they leave behind. A personal collection of things that made you think.", path: "reading / notes-from-the-margins.md" },
];

function Arrow({ diagonal = false }: { diagonal?: boolean }) {
  return <svg viewBox="0 0 24 24" width="21" height="21" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
    <path d={diagonal ? "M6 18 18 6M6 6h12v12" : "M4 12h16m-6-6 6 6-6 6"} /></svg>;
}

export default function LandingPage({ appHref = "/" }: { appHref?: string }) {
  const [selected, setSelected] = useState(0);
  const example = examples[selected];

  return <div className="page-landing" id="top">
    <a className="landing-skip" href="#landing-main">Skip to content</a>
    <header className="landing-nav">
      <a className="page-wordmark" href="#top" aria-label="Page home">Page<span className="page-fold" aria-hidden="true" /></a>
      <nav aria-label="Landing page navigation"><a className="landing-nav-link" href="#how-it-works">how it works</a><a className="landing-nav-link" href="#the-library">the library</a>
        <a className="landing-auth-link" href="/login/">Log In</a><a className="landing-auth-link landing-signup" href="/signup/">Sign Up</a>
        <a className="landing-outline" href={appHref}>Open App <Arrow diagonal /></a></nav>
    </header>

    <main id="landing-main">
      <section className="landing-hero" aria-labelledby="hero-title">
        <div className="landing-art"><img src={heroImage} alt="A stack of clothbound books with an open book and loose pages taking flight" width="1254" height="1254" fetchPriority="high" />
          <span className="art-caption">a little knowledge goes a long way.</span></div>
        <div className="hero-copy"><p className="landing-kicker"><span />YOUR PERSONAL KNOWLEDGE SPACE</p>
          <h1 id="hero-title"><span>a home for</span><span>your</span><span>thoughts<span className="orange-period">.</span></span></h1>
          <p className="hero-description">Everything you’ve learned. <br />Everything you’re still figuring out. <br /><strong>All on the same Page.</strong></p>
          <div className="hero-cta"><a className="landing-orange" href={appHref}>turn a Page <Arrow /></a><p>open the workspace preview. make yourself at home.</p></div>
        </div>
        <a href="#how-it-works" className="landing-scroll"><span>THERE’S MORE TO THE STORY</span><span aria-hidden="true">↓</span></a>
      </section>

      <div className="landing-belt" aria-label="Page capabilities"><span>plain Markdown</span><span aria-hidden="true">✳</span><span>your files, your control</span><span aria-hidden="true">✳</span><span>a growing library</span><span aria-hidden="true">✳</span><span>semantic indexing</span><span aria-hidden="true">✳</span><span>local first</span></div>

      <section className="landing-story landing-section" id="how-it-works" aria-labelledby="story-title">
        <div className="section-label"><span>01 / THE IDEA</span><span>THINK OUT LOUD. KEEP THE GOOD PARTS.</span></div>
        <div className="story-intro"><h2 id="story-title">the little things.<br />the big picture.</h2><div><p>A thought in the margins. A note from a meeting. An idea that shows up at the wrong time.</p>
          <p>Page gives them a place to belong. Your Markdown notes become books in a personal library—ready to revisit, build on, and find again.</p></div></div>
        <ol className="landing-steps"><li><span className="step-number">01</span><h3>keep a thought.</h3><p>Start with a Markdown note. Your writing stays in files you own, in a vault on your device.</p></li>
          <li><span className="step-number">02</span><h3>build your shelf.</h3><p>Index your vault and watch your notes become books. A little more context, a little more perspective.</p></li>
          <li><span className="step-number">03</span><h3>find it again.</h3><p>Browse your books and collections. Semantic indexing prepares your notes for finding meaning beyond exact words.</p></li></ol>
      </section>

      <section className="landing-library landing-section" id="the-library" aria-labelledby="library-title">
        <div className="section-label"><span>02 / THE LIBRARY</span><span>A SHELF THAT GROWS WITH YOU.</span></div>
        <div className="library-demo-layout"><div className="library-demo-copy"><h2 id="library-title">your mind.<br />with a <br />bookshelf.</h2><p>A place for the things you know, and room for everything you haven’t discovered yet.</p>
          <a className="landing-text-link" href={appHref}>take a look inside <Arrow diagonal /></a></div>
          <div className="landing-demo"><div className="demo-topbar"><span className="demo-brand">Page</span><span className="demo-label">SAMPLE LIBRARY</span><span className="demo-dots" aria-hidden="true">● ● ●</span></div>
            <div className="demo-main"><p className="demo-eyebrow">A FEW THOUGHTS WORTH KEEPING</p><h3>Your library.</h3>
              <div className="demo-shelf">{examples.map((book, index) => <button key={book.title} className={`demo-book demo-book--${book.color}${selected === index ? " is-selected" : ""}`} onClick={() => setSelected(index)} aria-pressed={selected === index} aria-label={`Read sample: ${book.title}`}>
                <span>{book.category}</span><strong>{book.title}</strong><span className="demo-book-symbol" aria-hidden="true">✳</span><small>THOUGHTS, COLLECTED.</small></button>)}<div className="demo-bookend" aria-hidden="true" /></div>
              <div className="demo-plank" /><div className="demo-reading" aria-live="polite"><span>{example.category}</span><h4>{example.title}</h4><p>{example.text}</p><small>{example.path}</small></div>
              <p className="demo-instruction">Pick a book. There’s a thought inside.</p></div>
          </div></div>
      </section>

      <section className="landing-questions landing-section" aria-labelledby="questions-title"><div className="section-label"><span>03 / A FEW GOOD QUESTIONS</span><span>BEFORE YOU TURN THE PAGE.</span></div>
        <div className="questions-layout"><h2 id="questions-title">good to <br />know.</h2><div className="landing-faq">
          <details><summary>Where do my notes live?<span aria-hidden="true">+</span></summary><p>In your own Markdown vault on your device. Page builds a local index around your files; the files remain the source of truth.</p></details>
          <details><summary>Can I bring an existing Markdown vault?<span aria-hidden="true">+</span></summary><p>Yes. The core can create a Page vault in an existing folder of Markdown notes without replacing the notes. Connect that vault to the desktop workspace and index it to populate your shelf.</p></details>
          <details><summary>Can I ask AI about my library?<span aria-hidden="true">+</span></summary><p>The question box is ready for local drafts. Gemini integration is planned, but questions aren’t sent to an AI service yet. Semantic indexing and a development search API are already implemented.</p></details>
          <details><summary>Is the desktop app ready to download?<span aria-hidden="true">+</span></summary><p>Page is in development. The React workspace runs inside a Tauri desktop shell, and the Python core currently starts separately. A self-contained desktop installer is still being prepared. You can explore the workspace preview now.</p></details>
        </div></div>
      </section>

      <section className="landing-final" aria-labelledby="final-title"><p>YOUR NEXT IDEA NEEDS A PLACE TO START.</p><h2 id="final-title">make room<br />for what’s next<span>.</span></h2><a className="landing-orange" href={appHref}>turn a Page <Arrow /></a><small>A workspace preview. A whole lot of possibility.</small></section>
    </main>

    <footer className="landing-footer"><a className="page-wordmark" href="#top">Page<span className="page-fold" aria-hidden="true" /></a><span>a personal space for a curious mind.</span>
      <nav aria-label="Footer navigation"><a href="#how-it-works">how it works</a><a href="https://github.com/jtdao24/page" target="_blank" rel="noreferrer">the project <Arrow diagonal /></a><a href="#top">back to top ↑</a></nav></footer>
  </div>;
}
