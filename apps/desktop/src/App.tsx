import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { bookAppearance, collectionOf, filterNotes, PREVIEW_NOTES } from "./library";
import type { ContextNote } from "./library";
import { useCore } from "./useCore";
import { AccountSettings } from "./auth/AccountSettings";
import { useAuth } from "./auth/AuthProvider";
import { AuthContent, authPageCopy } from "./auth/AuthPage";
import { authStatusLabel } from "./auth/service";
import { resolveAuthRoute } from "./auth/routes";
import type { AuthRoute } from "./auth/routes";
import "./auth/auth.css";

type IconName = "books" | "clock" | "search" | "plus" | "arrow" | "spark" | "settings" | "close" | "leaf" | "chevron" | "profile";
function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    books: <><path d="M4 4h4v16H4zM10 4h4v16h-4zM16 5l4-1 3 15-4 1z" /><path d="M4 8h4m2 8h4" /></>,
    clock: <><circle cx="12" cy="12" r="8" /><path d="M12 7v5l3 2" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z" /><path d="M20 3v4m-2-2h4" /></>,
    settings: <><path d="M4 7h16M4 17h16" /><circle cx="8" cy="7" r="2.5" /><circle cx="16" cy="17" r="2.5" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    leaf: <><path d="M19 4C8 3 3 8 6 15s14 4 13-11Z" /><path d="M5 20 15 9" /></>,
    chevron: <path d="m9 6 6 6-6 6" />,
    profile: <><circle cx="12" cy="8" r="4" /><path d="M4 21v-2a8 8 0 0 1 16 0v2" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

function Modal({ title, children, onClose, className = "" }: { title: string; children: ReactNode; onClose: () => void; className?: string }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog ref={ref} className={`modal ${className}`} aria-labelledby="modal-title" onCancel={onClose}
    onClick={(event) => { if (event.target === event.currentTarget) {
      const bounds = event.currentTarget.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
    } }}>
    <div className="modal-heading"><h2 id="modal-title">{title}</h2>
      <button className="icon-button" onClick={onClose} aria-label="Close dialog"><Icon name="close" /></button></div>
    {children}
  </dialog>;
}

function Book({ note, position, selected, onSelect }: { note: ContextNote; position: number; selected: boolean; onSelect: () => void }) {
  const appearance = bookAppearance(note.id);
  const face = position === 0;
  const style = { "--book-height": `${appearance.height}px`, "--book-width": `${appearance.width}px`,
    "--book-delay": `${Math.min(position, 10) * 35}ms` } as CSSProperties;
  return <button type="button" style={style} className={`book book--${appearance.color}${face ? " book--face" : ""}${selected ? " book--selected" : ""}`}
    onClick={onSelect} aria-label={`Open ${note.title}`} aria-pressed={selected} title={note.title}>
    {face ? <><span className="book-face-category">{collectionOf(note)}</span>
      <span className="book-face-title">{note.title}</span><span className="book-face-mark"><Icon name="leaf" size={32} /></span>
      <span className="book-face-footer">A COLLECTION OF THOUGHTS</span></>
      : <><span className="book-spine-rule" /><span className="book-spine-title">{note.title}</span>
        <span className="book-spine-number">{String(position + 1).padStart(2, "0")}</span></>}
  </button>;
}

function readDraft() {
  try { return typeof window === "undefined" ? "" : localStorage.getItem("page.question-draft") ?? ""; }
  catch { return ""; }
}

function App() {
  const core = useCore();
  const auth = useAuth();
  const [view, setView] = useState<"library" | "recent">("library");
  const [query, setQuery] = useState("");
  const [collection, setCollection] = useState("All collections");
  const [shelfPage, setShelfPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [modal, setModal] = useState<"connect" | "add" | "account" | AuthRoute | null>(null);
  const authRoute = resolveAuthRoute(modal ?? "");
  const [token, setToken] = useState("");
  const [draft, setDraft] = useState(readDraft);
  const [draftSaved, setDraftSaved] = useState(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  const preview = core.notes === null;
  const notes = core.notes ?? PREVIEW_NOTES;
  const collections = [...new Set(notes.map(collectionOf))].sort();
  const activeCollection = collections.includes(collection) ? collection : "All collections";
  const visible = filterNotes(notes, query, activeCollection, view === "recent");
  const pageCount = Math.max(1, Math.ceil(visible.length / 8));
  const currentPage = Math.min(shelfPage, pageCount - 1);
  const pageNotes = visible.slice(currentPage * 8, (currentPage + 1) * 8);
  const selected = pageNotes.find((note) => note.id === selectedId) ?? pageNotes[0] ?? null;
  const shelves = [pageNotes];

  const updateDraft = (value: string) => {
    setDraft(value);
    try { localStorage.setItem("page.question-draft", value); setDraftSaved(true); }
    catch { setDraftSaved(false); }
  };
  const prompt = (value: string) => { updateDraft(value); composer.current?.focus(); };

  return <div className="workspace">
    <aside className="sidebar" aria-label="Workspace navigation">
      <a className="brand" href="#library" onClick={() => setView("library")}>
        <span className="brand-mark"><Icon name="books" size={24} /></span><h1>Page</h1><span className="brand-dot" /></a>
      <div className="workspace-label"><span className="workspace-avatar">P</span><span>Personal workspace<small>A home for your ideas</small></span></div>
      <p className="nav-eyebrow">YOUR WORKSPACE</p>
      <nav>
        <button aria-label="Your library" aria-current={view === "library" ? "page" : undefined} className={`nav-item${view === "library" ? " active" : ""}`} onClick={() => { setView("library"); setShelfPage(0); }}>
          <Icon name="books" /><span>Your library</span><span className="nav-count">{notes.length}</span></button>
        <button aria-label="Recent additions" aria-current={view === "recent" ? "page" : undefined} className={`nav-item${view === "recent" ? " active" : ""}`} onClick={() => { setView("recent"); setShelfPage(0); }}>
          <Icon name="clock" /><span>Recent additions</span></button>
      </nav>
      <div className="sidebar-note"><Icon name="leaf" size={24} /><p>Good ideas deserve<br />a place to grow.</p><span>One page at a time.</span></div>
      <div className="sidebar-footer">
        <button className="nav-item profile-button" aria-label="Profile and account settings" onClick={() => setModal("account")}><Icon name="profile" /><span>Profile & account</span></button>
        <p className="profile-status">{authStatusLabel(auth.state)}</p>
        <button className="nav-item" aria-label="Vault settings" onClick={() => setModal("connect")}><Icon name="settings" /><span>Vault settings</span></button>
        <div className="connection-status"><span className={`status-dot${core.error ? " status-dot--error" : !preview ? " status-dot--live" : ""}`} />
          {core.error ? "Connection interrupted" : core.status?.state === "running" ? "Adding to your shelves…" : preview ? "Preview workspace" : "Connected to your vault"}</div>
        <span className="local-label">LOCAL FIRST. YOURS ALWAYS.</span>
      </div>
    </aside>

    <main className="main-content" id="library">
      <header className="topbar"><div className="breadcrumbs">Workspace <Icon name="chevron" size={13} /><span>{view === "library" ? "Your library" : "Recent additions"}</span></div>
        <button className="workspace-button" onClick={() => setModal("connect")}><span className="tiny-avatar">P</span>{core.status?.vault ?? "Personal vault"}<Icon name="chevron" size={13} /></button></header>
      <div className="dashboard">
        <section className="library-heading">
          <div><p className="eyebrow">A SPACE FOR WHAT YOU KNOW</p><h2>{view === "library" ? "Your library" : "Recently collected"}<span className="heading-period">.</span></h2>
            <p className="subtitle">A few thoughts today. A world of possibilities tomorrow.</p></div>
          <button className="button button-primary" onClick={() => setModal("add")}><Icon name="plus" size={17} />Add context</button>
        </section>

        {preview && <div className="preview-banner"><span><span className="preview-badge">PREVIEW</span>A glimpse of what your library can become.</span>
          <button onClick={() => setModal("connect")}>Connect your vault <Icon name="arrow" size={15} /></button></div>}
        {core.error && <p className="inline-error" role="alert">{core.error} <button onClick={() => setModal("connect")}>Connection settings</button></p>}
        {core.status?.state === "running" && <div className="indexing-strip" role="status">
          <span>Indexing your notes · {core.status.phase}</span><progress value={core.status.completed} max={Math.max(core.status.total, 1)} aria-label="Notes scanned" />
          <span>{core.status.completed}/{core.status.total}</span></div>}
        {core.status?.error && <p className="inline-error" role="alert">{core.status.error}</p>}

        <div className="library-toolbar"><div className="library-count"><Icon name="books" size={17} /><span>{visible.length} {visible.length === 1 ? "book" : "books"}</span><span className="toolbar-divider" /><span className="muted">{preview ? "Sample context" : "Collected context"}</span></div>
          <div className="library-filters"><label className="search-field"><Icon name="search" size={16} /><input type="search" placeholder="Find a book…" aria-label="Search your library" value={query} onChange={(event) => { setQuery(event.target.value); setShelfPage(0); }} /></label>
            <select aria-label="Filter by collection" value={activeCollection} onChange={(event) => { setCollection(event.target.value); setShelfPage(0); }}><option>All collections</option>{collections.map((name) => <option key={name}>{name}</option>)}</select></div>
        </div>

        <div className="library-layout">
          <section className="bookcase" aria-label="Context bookshelf">
            {shelves.map((shelf, row) => <div className="shelf-row" key={row}>
              <div className="shelf-books">{shelf.map((note, column) => <Book key={note.id} note={note} position={row * 8 + column} selected={selected?.id === note.id} onSelect={() => setSelectedId(note.id)} />)}
                {shelf.length === 0 && <div className="empty-shelf"><Icon name="books" size={30} /><h3>{notes.length ? "Nothing on this shelf yet" : "Your next chapter starts here"}</h3><p>{notes.length ? "Try another search or collection." : "Add Markdown notes to your vault, then index them to grow your library."}</p>
                  <button className="text-button" onClick={() => notes.length ? (setQuery(""), setCollection("All collections")) : setModal("add")}>{notes.length ? "Clear filters" : "Add your first context"}<Icon name="arrow" size={15} /></button></div>}
              </div><div className="shelf-plank"><span /></div>
            </div>)}
            <div className="shelf-caption"><Icon name="leaf" size={14} /><span>Your library grows with every note you collect.</span><span className="shelf-caption-count">{notes.length.toString().padStart(2, "0")} VOLUMES</span></div>
            {pageCount > 1 && <nav className="shelf-pagination" aria-label="Bookshelf pages"><button className="icon-button previous-shelf" aria-label="Previous shelf" disabled={currentPage === 0} onClick={() => setShelfPage(currentPage - 1)}><Icon name="arrow" size={15} /></button>
              <span aria-live="polite">Shelf {currentPage + 1} of {pageCount}</span><button className="icon-button" aria-label="Next shelf" disabled={currentPage === pageCount - 1} onClick={() => setShelfPage(currentPage + 1)}><Icon name="arrow" size={15} /></button></nav>}
          </section>

          <aside className="reading-panel" aria-labelledby="reading-heading"><p className="eyebrow" id="reading-heading">ON YOUR DESK</p>
            {selected ? <><span className={`reading-category category--${bookAppearance(selected.id).color}`}>{collectionOf(selected)}</span>
              <h3>{selected.title}</h3><div className="reading-rule" /><p className="reading-excerpt">{selected.excerpt || "This note is waiting for its first words."}</p>
              <div className="reading-meta"><span>{selected.chunks} {selected.chunks === 1 ? "passage" : "passages"}</span><span>{preview ? "Sample note" : "Markdown note"}</span></div>
              <p className="note-path" title={selected.path}>{selected.path}</p>
              <button className="text-button" onClick={() => prompt(`Help me explore the ideas in “${selected.title}”.`)}>Ask about this book <Icon name="arrow" size={15} /></button></>
              : <div className="reading-empty"><Icon name="leaf" size={30} /><p>A thought worth revisiting will find its way here.</p></div>}
          </aside>
        </div>

        <section className="conversation" aria-labelledby="conversation-heading"><div className="conversation-heading"><span className="spark-circle"><Icon name="spark" size={20} /></span><div><h2 id="conversation-heading">Where will your curiosity take you?</h2><p>Start with a question. Bring your context along.</p></div></div>
          <form className="composer" onSubmit={(event) => event.preventDefault()}>
            <label className="sr-only" htmlFor="question">Ask a question about your context</label>
            <textarea id="question" ref={composer} value={draft} onChange={(event) => updateDraft(event.target.value)} placeholder="Connect a few ideas, explore a question, or start something new…" rows={3} maxLength={12000} />
            <div className="composer-footer"><span className="composer-context"><Icon name="books" size={15} />{preview ? "Your context, connected" : `${notes.length} books in your library`}</span>
              <div className="composer-action"><span className="coming-soon"><span className="status-dot" />Gemini · coming soon</span><button className="send-button" disabled aria-label="Send question — Gemini is not connected yet" title="Gemini backend connection is coming soon"><Icon name="arrow" size={18} /></button></div></div>
          </form>
          <div className="prompt-suggestions"><span>A LITTLE INSPIRATION</span>{["Find connections in my notes", "What should I explore next?", "Help me develop an idea"].map((suggestion) => <button key={suggestion} onClick={() => prompt(suggestion)}>{suggestion}<Icon name="arrow" size={12} /></button>)}</div>
          <p className="draft-status" role="status">{draft ? draftSaved ? "Draft saved on this device. Nothing has been sent." : "Draft is available in this session. Browser storage is unavailable." : "A quiet space to think. Your notes stay yours."}</p>
        </section>
        <footer className="dashboard-footer"><span>Made for a mind that keeps exploring.</span><span>PAGE <span className="footer-star">✳</span> YOUR PERSONAL KNOWLEDGE SPACE</span></footer>
      </div>
    </main>

    {(modal === "connect" || modal === "account") && <Modal title="Workspace settings" onClose={() => setModal(null)}>
      <nav className="settings-tabs" aria-label="Settings sections"><button type="button" aria-pressed={modal === "connect"} onClick={() => setModal("connect")}>Vault</button><button type="button" aria-pressed={modal === "account"} onClick={() => setModal("account")}>Account</button></nav>
      {modal === "account" ? <AccountSettings onNavigate={setModal} /> : <>
      <p className="modal-description">Connect your Markdown vault to bring your own books to these shelves.</p>
      <form className="connection-form" onSubmit={(event) => { event.preventDefault(); core.connect(token); }}>
        <label htmlFor="session-token">Core session token</label><input id="session-token" type="password" autoComplete="off" value={token} placeholder="Paste your local service’s token" onChange={(event) => setToken(event.target.value)} />
        <p className="field-hint">Start the local Page core service for your vault, then use the session token it provides. Your token isn’t saved.</p>
        <button className="button button-primary" disabled={!token.trim() || core.pending}>{core.session && !core.status && !core.error ? "Connecting…" : "Connect vault"}<Icon name="arrow" size={16} /></button>
      </form>
      {core.error && <p className="inline-error" role="alert">{core.error}</p>}
      {core.status && <div className="vault-details"><span className="eyebrow">{core.status.vault}</span><p>{core.status.state === "running" ? `Indexing · ${core.status.phase}` : "Your vault is connected."}</p>
        <p className="field-hint">{core.status.embedded} passages embedded · {core.status.reused} cached vectors reused · {core.status.skipped} notes unchanged</p>
        <div className="modal-actions"><button className="button button-primary" disabled={core.pending || core.status.state === "running"} onClick={() => { void core.index(false); }}>Index changes</button>
          <button className="button button-secondary" disabled={core.pending || core.status.state === "running"} onClick={() => { void core.index(true); }}>Rebuild index</button>
          <button className="text-button" onClick={() => { core.disconnect(); setToken(""); }}>Disconnect</button></div>
        {core.status.error && <p className="inline-error" role="alert">{core.status.error}</p>}
      </div>}
      </>}
    </Modal>}
    {authRoute && <Modal key={authRoute} title={authPageCopy[authRoute].title} className="auth-dialog" onClose={() => setModal(null)}>
      <p className="auth-subtitle">{authPageCopy[authRoute].subtitle}</p>
      <AuthContent route={authRoute} onNavigate={setModal} onContinue={() => setModal(null)} />
      <div className="auth-switch"><button className="text-button" onClick={() => setModal(null)}>Continue to local workspace →</button><br /><button className="text-button" onClick={() => setModal("account")}>Return to account settings</button></div>
    </Modal>}
    {modal === "add" && <Modal title="Make room for a new idea" onClose={() => setModal(null)}>
      <span className="add-illustration"><Icon name="books" size={40} /><Icon name="plus" size={20} /></span>
      <p className="modal-description">Every Markdown note becomes a book in your library. Add a <strong>.md</strong> file to your vault, then index your changes to put it on the shelf.</p>
      <p className="field-hint">Your original files stay in your vault. New notes, edits, and renames appear after indexing.</p>
      {core.status ? <button className="button button-primary" disabled={core.pending || core.status.state === "running"} onClick={() => { void core.index(false); setModal(null); }}>Index my notes<Icon name="arrow" size={16} /></button>
        : <button className="button button-primary" onClick={() => setModal("connect")}>Connect your vault<Icon name="arrow" size={16} /></button>}
    </Modal>}
  </div>;
}

export default App;
