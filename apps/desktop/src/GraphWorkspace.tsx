import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent, ReactNode } from "react";
import { collectionOf, filterNotes, folderOf, foldersOf, PREVIEW_NOTES } from "./library";
import { EntryGraph } from "./EntryGraph";
import { EntryPane } from "./EntryPane";
import type { ContextNote } from "./library";
import { closeTab as removeTab, initialTabs, moveTab, openTab, paneOf, selectTab } from "./workspaceTabs";
import type { PaneSide, WorkspaceTabs } from "./workspaceTabs";
import { useCore } from "./useCore";
import { AccountSettings } from "./auth/AccountSettings";
import { useAuth } from "./auth/AuthProvider";
import { AuthContent, authPageCopy } from "./auth/AuthPage";
import { authStatusLabel } from "./auth/service";
import { resolveAuthRoute } from "./auth/routes";
import type { AuthRoute } from "./auth/routes";
import "./auth/auth.css";
import "./workspace.css";

type IconName = "graph" | "clock" | "search" | "plus" | "arrow" | "spark" | "settings" | "close" | "leaf" | "chevron" | "profile" | "panel" | "folder" | "file";
function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const paths: Record<IconName, ReactNode> = {
    graph: <><path d="m7 7 10 2M7 7l3 11m7-9-7 9" /><circle cx="7" cy="7" r="3" /><circle cx="17" cy="9" r="3" /><circle cx="10" cy="18" r="3" /></>,
    clock: <><circle cx="12" cy="12" r="8" /><path d="M12 7v5l3 2" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 4 4" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6" />,
    spark: <><path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z" /><path d="M20 3v4m-2-2h4" /></>,
    settings: <><path d="M4 7h16M4 17h16" /><circle cx="8" cy="7" r="2.5" /><circle cx="16" cy="17" r="2.5" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    leaf: <><path d="M19 4C8 3 3 8 6 15s14 4 13-11Z" /><path d="M5 20 15 9" /></>,
    chevron: <path d="m9 6 6 6-6 6" />,
    panel: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></>,
    folder: <path d="M3 7V5h6l2 2h10v13H3Z" />,
    file: <><path d="M5 3h9l5 5v13H5Z" /><path d="M14 3v6h5M8 13h8M8 17h6" /></>,
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

function readDraft() {
  try { return typeof window === "undefined" ? "" : localStorage.getItem("page.question-draft") ?? ""; }
  catch { return ""; }
}

function readSidebarPreference() {
  try {
    const stored = localStorage.getItem("page.sidebar-collapsed");
    if (stored !== null) return stored === "true";
  } catch { /* Layout still works when storage is unavailable. */ }
  return typeof window !== "undefined" && window.innerWidth <= 680;
}

function folderLabel(path: string) {
  return path ? path.split("/").join(" › ") : "Vault root";
}

function GraphWorkspace() {
  const core = useCore();
  const auth = useAuth();
  const [view, setView] = useState<"library" | "recent">("library");
  const [query, setQuery] = useState("");
  const [collection, setCollection] = useState("All collections");
  const [folderSelection, setFolderSelection] = useState<{ scope: string; path: string }>({ scope: "", path: "" });
  const [tabState, setTabState] = useState<{ scope: string; layout: WorkspaceTabs }>({ scope: "", layout: initialTabs() });
  const draggedTab = useRef<{ scope: string; id: string } | null>(null);
  const [dragScope, setDragScope] = useState<string | null>(null);
  const [dropSide, setDropSide] = useState<PaneSide | null>(null);
  const [lastOpenedId, setLastOpenedId] = useState<string | null>(null);
  const [modal, setModal] = useState<"connect" | "add" | "account" | AuthRoute | null>(null);
  const authRoute = resolveAuthRoute(modal ?? "");
  const [token, setToken] = useState("");
  const [draft, setDraft] = useState(readDraft);
  const [draftSaved, setDraftSaved] = useState(true);
  const composer = useRef<HTMLTextAreaElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarPreference);
  const toggleSidebar = useCallback(() => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    try { localStorage.setItem("page.sidebar-collapsed", String(next)); } catch { /* Session-only preference. */ }
  }, [sidebarCollapsed]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || document.querySelector("dialog[open]")) return;
      if ((event.metaKey || event.ctrlKey) && event.key === "\\") {
        event.preventDefault(); toggleSidebar();
      }
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [toggleSidebar]);
  const preview = core.notes === null;
  const notes = core.notes ?? PREVIEW_NOTES;
  const scope = `${core.session ?? "local-preview"}:${preview ? "preview" : "vault"}`;
  // A vault/session change unmounts its entry panels and aborts pending reads.
  const layout = tabState.scope === scope ? tabState.layout : initialTabs();
  const tabs = layout.entries;
  const activeId = layout.selected[layout.focused];
  const split = layout.panes.right.length > 0;
  const dragging = dragScope === scope;
  const tabId = (id: string) => `workspace-tab-${id}`;
  const changeLayout = (change: (state: WorkspaceTabs) => WorkspaceTabs) => {
    setTabState((previous) => ({ scope, layout: change(previous.scope === scope ? previous.layout : initialTabs()) }));
  };
  const activateTab = (id: string) => {
    changeLayout((state) => selectTab(state, id));
  };
  const showGraph = (nextView: "library" | "recent" = "library") => { setView(nextView); activateTab("graph"); };
  const closeTab = (id: string) => {
    const next = removeTab(layout, id);
    changeLayout(() => next);
    setTimeout(() => document.getElementById(tabId(next.selected[next.focused]))?.focus(), 0);
  };
  const endDrag = () => { draggedTab.current = null; setDragScope(null); setDropSide(null); };
  const startDrag = (event: DragEvent, id: string) => {
    draggedTab.current = { scope, id };
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("application/x-page-tab", id);
    setDragScope(scope);
  };
  const acceptDrag = (event: DragEvent, side: PaneSide) => {
    if (draggedTab.current?.scope !== scope) return;
    event.preventDefault(); event.dataTransfer.dropEffect = "move"; setDropSide(side);
  };
  const transferTab = (id: string, side: PaneSide, createSplit = false) => {
    changeLayout((state) => moveTab(state, id, side, createSplit));
    setTimeout(() => document.getElementById(tabId(id))?.focus(), 0);
  };
  const dropTab = (event: DragEvent, side: PaneSide, createSplit = false) => {
    const dragged = draggedTab.current;
    if (dragged?.scope !== scope) return;
    event.preventDefault(); event.stopPropagation();
    transferTab(dragged.id, side, createSplit); endDrag();
  };
  const noteCollections = new Map<string, ContextNote[]>();
  for (const note of notes) {
    const name = collectionOf(note);
    const members = noteCollections.get(name) ?? [];
    members.push(note);
    noteCollections.set(name, members);
  }
  const collections = [...noteCollections.keys()].sort();
  const activeCollection = collections.includes(collection) ? collection : "All collections";
  const visible = filterNotes(notes, query, activeCollection, view === "recent");
  const folders = foldersOf(notes);
  const populatedFolders = [...new Set(notes.map(folderOf))].sort();
  const defaultFolder = populatedFolders[0] ?? "";
  const selectedFolder = folderSelection.scope === scope && folders.includes(folderSelection.path) ? folderSelection.path : defaultFolder;
  const folderFiles = notes.filter((note) => folderOf(note) === selectedFolder).sort((a, b) => a.path.localeCompare(b.path));

  const updateDraft = (value: string) => {
    setDraft(value);
    try { localStorage.setItem("page.question-draft", value); setDraftSaved(true); }
    catch { setDraftSaved(false); }
  };
  const prompt = (value: string) => { updateDraft(value); composer.current?.focus(); };

  const openEntry = (note: ContextNote) => {
    setLastOpenedId(note.id);
    setFolderSelection({ scope, path: folderOf(note) });
    changeLayout((state) => openTab(state, note));
    setTimeout(() => document.getElementById(tabId(note.id))?.focus(), 0);
  };

  return <div className={`workspace${sidebarCollapsed ? " workspace--sidebar-collapsed" : ""}`}>
    <header className="workspace-brandbar">
      <a className="brand" href="#library" onClick={() => showGraph()}><h1>Page</h1></a>
    </header>
    <nav className="workspace-tools" aria-label="Workspace tools">
      <button className="workspace-tool" aria-label="Go to graph" title="Page graph" onClick={() => showGraph()}><Icon name="graph" size={19} /></button>
      <button className={`workspace-tool${!sidebarCollapsed ? " is-active" : ""}`} aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        aria-expanded={!sidebarCollapsed} aria-controls="vault-sidebar" title="Toggle sidebar (⌘/Ctrl + \)" onClick={toggleSidebar}><Icon name="panel" size={18} /></button>
      <button className="workspace-tool" aria-label="Focus library search" title="Search your library" onClick={() => { showGraph(view); setTimeout(() => searchInput.current?.focus(), 0); }}><Icon name="search" size={18} /></button>
      <button className="workspace-tool" aria-label="Add Markdown context" title="Add context" onClick={() => setModal("add")}><Icon name="plus" size={18} /></button>
      <button className="workspace-tool" aria-label="Profile and account settings" title={`Profile · ${authStatusLabel(auth.state)}`} onClick={() => setModal("account")}><Icon name="profile" size={18} /></button>
      <button className="workspace-tool" aria-label="Vault settings" title="Vault settings" onClick={() => setModal("connect")}><Icon name="settings" size={18} /></button>
    </nav>
    <aside className="sidebar" id="vault-sidebar" aria-label="Vault navigation" hidden={sidebarCollapsed}>
      <button className="sidebar-vault" onClick={() => setModal("connect")} title="Open vault settings"><Icon name="folder" size={15} /><span>{core.status?.vault ?? "Personal vault"}</span><Icon name="chevron" size={12} /></button>
      <nav className="sidebar-views" aria-label="Library views">
        <button aria-label="Your graph" aria-current={activeId === "graph" && view === "library" ? "page" : undefined} className={`nav-item${activeId === "graph" && view === "library" ? " active" : ""}`} onClick={() => showGraph()}>
          <Icon name="graph" size={16} /><span>Your graph</span><span className="nav-count">{notes.length}</span></button>
        <button aria-label="Recent entries" aria-current={activeId === "graph" && view === "recent" ? "page" : undefined} className={`nav-item${activeId === "graph" && view === "recent" ? " active" : ""}`} onClick={() => showGraph("recent")}>
          <Icon name="clock" size={16} /><span>Recent entries</span></button>
      </nav>
      <div className="vault-files" key={`${scope}:${selectedFolder}`}><div className="vault-files-heading"><span title={selectedFolder || "Vault root"}>{folderLabel(selectedFolder)}</span><span>{folderFiles.length}</span></div>
        {folderFiles.map((note) => <button className={`vault-note${lastOpenedId === note.id ? " is-selected" : ""}`} key={note.id}
          aria-label={`Read ${note.title}`} title={`${note.title} · ${note.path}`} onClick={() => openEntry(note)}><Icon name="file" size={13} /><span>{note.path.slice(note.path.lastIndexOf("/") + 1)}</span></button>)}
        {!folderFiles.length && <p className="vault-empty">{notes.length ? "No Markdown files in this folder. Choose another folder below." : "Your Markdown files will appear here."}</p>}
      </div>
      <div className="sidebar-footer">
        <div className="connection-status"><span className={`status-dot${core.error ? " status-dot--error" : !preview ? " status-dot--live" : ""}`} />
          {core.error ? "Connection interrupted" : core.status?.state === "running" ? "Updating your network…" : preview ? "Preview workspace" : "Connected to your vault"}</div>
        <p className="profile-status">{authStatusLabel(auth.state)}</p>
        <div className="folder-switcher">
          <label htmlFor="sidebar-folder">Folder</label>
          <div className="folder-switcher-field"><Icon name="folder" size={15} />
            <select id="sidebar-folder" aria-label="Switch folder" title={selectedFolder || "Vault root"} value={selectedFolder}
              onChange={(event) => setFolderSelection({ scope, path: event.target.value })}>
              {folders.map((path) => <option key={path} value={path}>{folderLabel(path)}</option>)}
            </select>
          </div>
        </div>
      </div>
    </aside>

    <main className={`main-content${split ? " main-content--split" : ""}`} id="library"
      onDragOver={(event) => { if (draggedTab.current?.scope !== scope) { event.preventDefault(); event.dataTransfer.dropEffect = "none"; } }}
      onDrop={(event) => event.preventDefault()}>
      {(["left", "right"] as const).filter((side) => side === "left" || split).map((side) => {
        const ids = layout.panes[side];
        const selected = layout.selected[side];
        const splitLabel = split ? "Move active tab to other pane" : "Split active tab to right";
        return <header key={side} className={`topbar pane-${side}${layout.focused === side ? " pane-focused" : ""}`}
          onFocusCapture={(event) => activateTab((event.target as HTMLElement).closest<HTMLElement>("[data-tab-id]")?.dataset.tabId ?? selected)}
          onDragOver={(event) => acceptDrag(event, side)} onDrop={(event) => dropTab(event, side)}>
          <div className="workspace-tabs" role="tablist" aria-label={split ? `${side === "left" ? "Left" : "Right"} pane tabs` : "Workspace tabs"}
            onKeyDown={(event) => {
              if (!(event.target as Element).matches('[role="tab"]')) return;
              const current = ids.indexOf(selected);
              const next = event.key === "ArrowRight" ? ids[(current + 1) % ids.length]
                : event.key === "ArrowLeft" ? ids[(current - 1 + ids.length) % ids.length]
                : event.key === "Home" ? ids[0] : event.key === "End" ? ids[ids.length - 1] : null;
              if (next) { event.preventDefault(); activateTab(next); document.getElementById(tabId(next))?.focus(); }
              if (event.key === "Delete" && selected !== "graph") { event.preventDefault(); closeTab(selected); }
              if (event.key === "Escape") endDrag();
            }}>
            {ids.map((id) => {
              const note = tabs.find((entry) => entry.id === id);
              const title = note?.title ?? "Graph";
              return <div className={`entry-tab${selected === id ? " is-active" : ""}`} key={id}>
                <button className="workspace-tab" role="tab" id={tabId(id)} data-tab-id={id} aria-selected={selected === id}
                  aria-controls={`workspace-panel-${id}`} tabIndex={selected === id ? 0 : -1} onClick={() => activateTab(id)}
                  draggable onDragStart={(event) => startDrag(event, id)} onDragEnd={endDrag}
                  title={`${note?.path ?? "Graph"} · Drag to either side to split`}>
                  <Icon name={note ? "file" : "graph"} size={14} /><span>{title}</span></button>
                {note && <button className="tab-close" type="button" aria-label={`Close ${title} tab`} onClick={() => closeTab(id)}><Icon name="close" size={12} /></button>}
              </div>;
            })}
          </div>
          <button className="pane-split-button" aria-label={splitLabel} title={splitLabel} disabled={tabs.length === 0}
            onClick={() => transferTab(selected, side === "left" ? "right" : "left")}><Icon name="panel" size={16} /></button>
        </header>;
      })}
      <section key="graph" role="tabpanel" id="workspace-panel-graph" aria-labelledby={tabId("graph")}
        className={`workspace-graph-panel pane-${paneOf(layout, "graph")}`}
        onPointerDown={() => activateTab("graph")} onFocusCapture={() => activateTab("graph")}
        hidden={layout.selected[paneOf(layout, "graph")] !== "graph"}>
      <div className="dashboard">
        <section className="library-heading">
          <div><p className="eyebrow">WORKSPACE / GRAPH</p><h2>{view === "library" ? "Your graph" : "Recent entries"}<span className="heading-period">.</span></h2>
            <p className="subtitle">Your knowledge, one connection at a time.</p></div>
          <button className="button button-primary" onClick={() => setModal("add")}><Icon name="plus" size={17} />Add context</button>
        </section>

        {preview && <div className="preview-banner"><span><span className="preview-badge">PREVIEW</span>A glimpse of what your library can become.</span>
          <button onClick={() => setModal("connect")}>Connect your vault <Icon name="arrow" size={15} /></button></div>}
        {core.error && <p className="inline-error" role="alert">{core.error} <button onClick={() => setModal("connect")}>Connection settings</button></p>}
        {core.status?.state === "running" && <div className="indexing-strip" role="status">
          <span>Indexing your notes · {core.status.phase}</span><progress value={core.status.completed} max={Math.max(core.status.total, 1)} aria-label="Notes scanned" />
          <span>{core.status.completed}/{core.status.total}</span></div>}
        {core.status?.error && <p className="inline-error" role="alert">{core.status.error}</p>}

        <div className="library-toolbar"><div className="library-count"><Icon name="graph" size={17} /><span>{visible.length} {visible.length === 1 ? "entry" : "entries"}</span><span className="toolbar-divider" /><span className="muted">{preview ? "Sample context" : "Collected context"}</span></div>
          <div className="library-filters"><label className="search-field"><Icon name="search" size={16} /><input ref={searchInput} type="search" placeholder="Find an entry…" aria-label="Search your library" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
            <select aria-label="Filter by collection" value={activeCollection} onChange={(event) => setCollection(event.target.value)}><option>All collections</option>{collections.map((name) => <option key={name}>{name}</option>)}</select></div>
        </div>

        <EntryGraph key={scope} notes={notes} visible={visible} selectedId={lastOpenedId} collection={activeCollection}
          onOpen={openEntry} onFilter={setCollection}
          emptyAction={() => { if (notes.length) { setQuery(""); setCollection("All collections"); } else setModal("add"); }} />

        <section className="conversation" aria-labelledby="conversation-heading"><div className="conversation-heading"><span className="spark-circle"><Icon name="spark" size={20} /></span><div><h2 id="conversation-heading">Ask your vault</h2><p>A question, with your notes close at hand.</p></div></div>
          <form className="composer" onSubmit={(event) => event.preventDefault()}>
            <label className="sr-only" htmlFor="question">Ask a question about your context</label>
            <textarea id="question" ref={composer} value={draft} onChange={(event) => updateDraft(event.target.value)} placeholder="Connect a few ideas, explore a question, or start something new…" rows={3} maxLength={12000} />
            <div className="composer-footer"><span className="composer-context"><Icon name="graph" size={15} />{preview ? "Your context, connected" : `${notes.length} entries in your vault`}</span>
              <div className="composer-action"><span className="coming-soon"><span className="status-dot" />Gemini · coming soon</span><button className="send-button" disabled aria-label="Send question — Gemini is not connected yet" title="Gemini backend connection is coming soon"><Icon name="arrow" size={18} /></button></div></div>
          </form>
          <div className="prompt-suggestions"><span>TRY A QUESTION</span>{["Find connections in my notes", "What should I explore next?", "Help me develop an idea"].map((suggestion) => <button key={suggestion} onClick={() => prompt(suggestion)}>{suggestion}<Icon name="arrow" size={12} /></button>)}</div>
          <p className="draft-status" role="status">{draft ? draftSaved ? "Draft saved on this device. Nothing has been sent." : "Draft is available in this session. Browser storage is unavailable." : "A quiet space to think. Your notes stay yours."}</p>
        </section>
        <footer className="dashboard-footer"><span>{notes.length} Markdown {notes.length === 1 ? "note" : "notes"}</span><span>Page · local workspace</span></footer>
      </div>
      </section>
      {tabs.map((note) => <section key={`${scope}:${note.id}`} role="tabpanel" id={`workspace-panel-${note.id}`}
        aria-labelledby={tabId(note.id)} className={`workspace-entry-panel pane-${paneOf(layout, note.id)}`}
        onPointerDown={() => activateTab(note.id)} onFocusCapture={() => activateTab(note.id)}
        hidden={layout.selected[paneOf(layout, note.id)] !== note.id}>
        <EntryPane note={note} session={core.session} preview={preview} onAsk={() => {
          updateDraft(`Help me explore the ideas in “${note.title}”.`);
          activateTab("graph"); setTimeout(() => composer.current?.focus(), 0);
        }} />
      </section>)}
      {dragging && <div className="split-drop-targets" onDragLeave={(event) => {
        if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDropSide(null);
      }}>
        {(["left", "right"] as const).map((side) => <div key={side} className={`split-drop-zone${dropSide === side ? " is-over" : ""}`}
          role="group" aria-label={`Drop tab in ${side} pane`} onDragOver={(event) => acceptDrag(event, side)}
          onDrop={(event) => dropTab(event, side, true)}><span>{split ? "Move to" : "Split to"} {side}<small>Release to place tab</small></span></div>)}
      </div>}
    </main>

    {(modal === "connect" || modal === "account") && <Modal title="Workspace settings" onClose={() => setModal(null)}>
      <nav className="settings-tabs" aria-label="Settings sections"><button type="button" aria-pressed={modal === "connect"} onClick={() => setModal("connect")}>Vault</button><button type="button" aria-pressed={modal === "account"} onClick={() => setModal("account")}>Account</button></nav>
      {modal === "account" ? <AccountSettings onNavigate={setModal} /> : <>
      <p className="modal-description">Connect your Markdown vault to populate your knowledge graph.</p>
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
      <span className="add-illustration"><Icon name="graph" size={40} /><Icon name="plus" size={20} /></span>
      <p className="modal-description">Every Markdown note becomes an entry in your graph. Add a <strong>.md</strong> file to your vault, then index your changes to add it to your network.</p>
      <p className="field-hint">Your original files stay in your vault. New notes, edits, and renames appear after indexing.</p>
      {core.status ? <button className="button button-primary" disabled={core.pending || core.status.state === "running"} onClick={() => { void core.index(false); setModal(null); }}>Index my notes<Icon name="arrow" size={16} /></button>
        : <button className="button button-primary" onClick={() => setModal("connect")}>Connect your vault<Icon name="arrow" size={16} /></button>}
    </Modal>}
  </div>;
}

export default GraphWorkspace;
