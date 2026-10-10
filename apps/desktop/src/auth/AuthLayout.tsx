import type { ReactNode } from "react";

export function AuthLayout({ title, subtitle, children, appHref = "/", homeHref = "/landing.html" }: {
  title: string; subtitle: string; children: ReactNode; appHref?: string; homeHref?: string;
}) {
  return <div className="auth-page">
    <a className="auth-skip" href="#auth-main">Skip to form</a>
    <header className="auth-header"><a className="auth-wordmark" href={homeHref} aria-label="Page home">Page<span aria-hidden="true" /></a>
      <a className="auth-open-app" href={appHref}>Open App <span aria-hidden="true">↗</span></a></header>
    <main className="auth-main" id="auth-main">
      <aside className="auth-story"><p className="auth-eyebrow">YOUR PERSONAL KNOWLEDGE SPACE</p>
        <h1>your ideas.<br />your place<span>.</span></h1><p className="auth-story-copy">A shelf for everything you know.<br />A little room for what comes next.</p>
        <div className="auth-paper" aria-hidden="true"><span>Page / a thought worth keeping</span><div /><div /><div /><strong>one page<br />at a time.</strong><span>LOCAL FIRST. YOURS ALWAYS.</span></div>
        <p className="auth-local-note">Your local vault doesn’t need an online account.<br /><a href={appHref}>Continue to your workspace →</a></p>
      </aside>
      <section className="auth-form-panel" aria-labelledby="auth-title"><p className="auth-eyebrow">A HOME FOR YOUR THOUGHTS</p>
        <h2 id="auth-title">{title}<span>.</span></h2><p className="auth-subtitle">{subtitle}</p>{children}</section>
    </main>
    <footer className="auth-footer"><span>Page — a personal space for a curious mind.</span><span>LOCAL WORKSPACE. OPTIONAL ACCOUNT.</span></footer>
  </div>;
}
