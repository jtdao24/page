import { lazy, Suspense, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from "react";
import { type WorkspaceController, backendReady, isDirty, mutationsBlocked, navigationBlocked } from "../workspace/controller";
import { useWorkspace } from "../workspace/useWorkspace";
import { buildTree } from "../workspace/tree";
import { describeSeparator } from "../workspace/text";
import { Dialog } from "./Dialog";
import { ErrorText } from "./ErrorText";
import { MarkdownEditor } from "./MarkdownEditor";
import { NotePathForm } from "./NotePathForm";
import { NoteTree } from "./NoteTree";
import { VaultForms } from "./VaultForms";
import { AskBar, focusAskBar } from "./AskBar";
import { type OpenSource, SourceViewer } from "./SourceViewer";
import { WebPageForm } from "./WebPageForm";
import type { SourceSummaryResponse } from "../core/types";
import { SemanticSearch } from "./SemanticSearch";
import { Icon, type IconName } from "./Icon";

const KnowledgeGraph = lazy(() => import("./KnowledgeGraph").then((module) => ({ default: module.KnowledgeGraph })));

const SHORTCUT = typeof navigator !== "undefined" && /Mac/.test(navigator.platform) ? "⌘" : "Ctrl+";
const GRAPH_MIN = 320;

/** A labeled sidebar action; collapsed sidebars show only the icon with a tooltip. */
function NavItem({ icon, label, ariaLabel, shortcut, active, disabled, onClick, controls }: {
  icon: IconName; label: string; ariaLabel?: string; shortcut?: string; active?: boolean; disabled?: boolean;
  onClick: () => void; controls?: string;
}) {
  return <button className="nav-item" aria-label={ariaLabel ?? label} title={shortcut ? `${label} · ${SHORTCUT}${shortcut}` : label}
    aria-pressed={active === undefined ? undefined : active} aria-controls={controls} disabled={disabled} onClick={onClick}>
    <Icon name={icon} size={17} /><span className="nav-label">{label}</span>
    {shortcut && <kbd className="nav-shortcut">{SHORTCUT}{shortcut}</kbd>}
  </button>;
}

type Modal = "vault" | "web" | "create" | "move" | "delete" | "convert" | "orphan" | "reload" | "overwrite" | "failed-move" | "reset" | null;

export function Workspace({ controller }: { controller: WorkspaceController }) {
  const state = useWorkspace(controller);
  const [modal, setModal] = useState<Modal>(null);
  const [searchVisible, setSearchVisible] = useState(false);
  const [graphVisible, setGraphVisible] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [graphWidth, setGraphWidth] = useState<number | null>(null);
  // A source stays open only while the same note and vault are current.
  const [opened, setOpened] = useState<{ source: OpenSource; noteKey: string | null; vaultId: string } | null>(null);
  const [sources, setSources] = useState<{ vaultId: string; items: SourceSummaryResponse[] } | null>(null);
  const split = useRef<HTMLDivElement>(null);
  const document = state.document;
  const blocked = mutationsBlocked(state) || state.vaultBusy;
  const navigation = navigationBlocked(state);
  const readyDocument = document?.status === "ready";

  useEffect(() => {
    const detach = controller.attach();
    void controller.start();
    return detach;
  }, [controller]);

  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((!event.metaKey && !event.ctrlKey) || event.altKey || event.shiftKey) return;
      const key = event.key.toLowerCase();
      if (!["s", "n", "o", "k"].includes(key)) return;
      event.preventDefault();
      if (event.repeat || modal !== null || controller.getState().guard !== null) return;
      const current = controller.getState();
      if (key === "k") { focusAskBar(); return; }
      if (key === "s" && !mutationsBlocked(current)) void controller.save();
      if (key === "o" && !navigationBlocked(current)) setModal("vault");
      if (key === "n" && !mutationsBlocked(current) && !navigationBlocked(current)) {
        void controller.guarded("create another note", () => setModal("create"));
      }
    }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  }, [controller, modal]);

  // PDFs, code and text files in the vault folder, refreshed whenever the note list reloads.
  const vaultId = state.vault?.id;
  const ready = backendReady(state);
  useEffect(() => {
    if (!vaultId || !ready || state.notes === null) return;
    let live = true;
    controller.listSources(vaultId).then((items) => { if (live) setSources({ vaultId, items }); }, () => {});
    return () => { live = false; };
  }, [controller, vaultId, ready, state.notes]);
  const sourceItems = sources !== null && sources.vaultId === vaultId ? sources.items : [];
  // Opening a note (from the tree, graph, search or a citation) closes the source viewer.
  const noteKey = document ? `${document.vaultId}:${document.noteId}` : null;
  const openSource = opened !== null && opened.noteKey === noteKey && opened.vaultId === vaultId ? opened.source : null;
  const viewing = openSource !== null && state.vault !== null;
  const setOpenSource = (source: OpenSource | null) =>
    setOpened(source === null || vaultId === undefined ? null : { source, noteKey, vaultId });

  function noteAction(action: "create" | "move" | "delete") {
    if (blocked || navigation) return;
    void controller.guarded(action === "create" ? "create another note" : `${action} this note`, () => setModal(action));
  }
  const cancel = () => setModal(null);

  // The graph split is resizable by pointer or arrow keys; it defaults to half the main area.
  function clampGraph(width: number) {
    const total = split.current?.clientWidth || 1200;
    return Math.round(Math.min(Math.max(width, GRAPH_MIN), Math.max(GRAPH_MIN, total - 360)));
  }
  function startResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const handle = event.currentTarget;
    handle.setPointerCapture?.(event.pointerId);
    const right = split.current?.getBoundingClientRect().right ?? window.innerWidth;
    const move = (moved: PointerEvent) => setGraphWidth(clampGraph(right - moved.clientX));
    const stop = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", stop); };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
  }
  function resizeByKey(event: ReactKeyboardEvent<HTMLDivElement>) {
    const step = event.key === "ArrowLeft" ? 40 : event.key === "ArrowRight" ? -40 : 0;
    if (step === 0) return;
    event.preventDefault();
    setGraphWidth((width) => clampGraph((width ?? (split.current?.clientWidth || 1200) / 2) + step));
  }
  const errors = [state.backendError, state.preferencesWriteError, state.listError, state.actionError?.error];

  return <main className="page-app flex h-screen min-h-0 flex-col">
    <header className="workspace-titlebar">
      <div className="page-wordmark"><Icon name="vault" size={17} /><h1>Page</h1></div>
      <span role="status" className="connection-state">
        <span className={`connection-dot ${backendReady(state) ? "is-ready" : ""}`} aria-hidden="true" />
        {state.phase === "unavailable" ? "Desktop runtime unavailable" : `Page Core: ${state.backend?.state ?? "starting"}`}
      </span>
      <button disabled={state.phase !== "active" || state.quitting || state.vaultBusy || state.backend?.state === "starting" || state.backend?.state === "stopping"}
        onClick={() => void controller.restart()}>Restart Core</button>
    </header>
    {state.phase === "unavailable" ? <section className="workspace-welcome">
      <div className="welcome-mark"><Icon name="vault" size={36} /></div>
      <h2>Run Page in the desktop application</h2>
      <p>The browser cannot access your vaults. Launch the Tauri desktop app with npm run tauri:dev.</p>
    </section> : <>
      <div className="workspace-notices max-h-40 shrink-0 overflow-auto px-4">
        {errors.map((error, index) => error && <p className="py-1 text-sm text-red-700" role="alert" key={index}><ErrorText error={error} /></p>)}
        {state.vaultError && modal !== "vault" && <p role="alert"><ErrorText error={state.vaultError} /></p>}
        {state.preferencesWarning && <p role="alert" className="text-sm">
          <ErrorText error={state.preferencesWarning} /> The settings file is preserved.
          <button onClick={() => setModal("reset")}>Reset Remembered Workspace</button>
        </p>}
        {state.message && <p role={state.message.tone === "error" ? "alert" : "status"} className="text-sm py-1">{state.message.text}</p>}
        {!backendReady(state) && state.phase === "active" && <button onClick={() => void controller.retryStart()}>Retry Startup</button>}
      </div>
      <div className="flex min-h-0 flex-1">
        <aside id="workspace-sidebar" className="workspace-sidebar" data-collapsed={sidebarCollapsed || undefined} aria-label="Vault and note navigation">
          <div className="sidebar-top">
            {!sidebarCollapsed && <button className="vault-switcher" disabled={navigation} title="Switch or create vault" onClick={() => setModal("vault")}>
              <span className="vault-name">{state.vault?.name ?? "No vault"}</span><span aria-hidden="true">⌄</span>
            </button>}
            <button className="collapse-toggle" aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"} title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-expanded={!sidebarCollapsed} aria-controls="workspace-sidebar" onClick={() => setSidebarCollapsed(!sidebarCollapsed)}><Icon name="sidebar" size={16} /></button>
          </div>
          <nav className="sidebar-nav" aria-label="Workspace tools">
            <NavItem icon="plus" label="New note" ariaLabel="New Note" shortcut="N" disabled={!state.vault || blocked || navigation} onClick={() => noteAction("create")} />
            <NavItem icon="search" label="Search" ariaLabel="Semantic search" active={searchVisible} disabled={!state.vault}
              onClick={() => { setSearchVisible(!searchVisible); setGraphVisible(false); }} />
            <NavItem icon="graph" label="Graph" ariaLabel="Knowledge graph" active={graphVisible} disabled={!state.vault}
              onClick={() => { setGraphVisible(!graphVisible); setSearchVisible(false); }} />
            <NavItem icon="ask" label="Ask" ariaLabel="Ask your notes" shortcut="K" disabled={!state.vault} onClick={focusAskBar} />
            <NavItem icon="globe" label="Add website" ariaLabel="Add website" disabled={!state.vault || blocked || navigation}
              onClick={() => void controller.guarded("save a web page", () => setModal("web"))} />
          </nav>
          {!sidebarCollapsed && state.vault && <section className="sidebar-files" aria-label="Files">
            <div className="sidebar-heading"><span>Files</span><span className="sidebar-count">{state.notes?.length ?? 0}</span>
              <button className="icon-button" aria-label="Refresh from Disk" title="Refresh from disk" disabled={blocked || navigation}
                onClick={() => void controller.refreshFromDisk()}><Icon name="refresh" size={13} /></button>
            </div>
            {state.notesLoading && <p role="status" className="sidebar-note">Loading notes…</p>}
            {state.notes?.length === 0 && <p className="sidebar-note">No notes yet. Create a note to begin.</p>}
            <NoteTree nodes={buildTree(state.notes ?? [], sourceItems)} selected={openSource ? openSource.id : document?.noteId}
              onOpenSource={(source) => setOpenSource({ id: source.id, relativePath: source.relative_path, kind: source.kind })} disabled={navigation || state.recovery !== null || state.unknown !== null}
              onSelect={(id) => { setOpenSource(null); void controller.selectNote(id); }} />
            {state.listError && <button onClick={() => void controller.reloadNotes()}>Retry Note List</button>}
          </section>}
          {!sidebarCollapsed && state.sessions.length > 1 && <section className="sidebar-section">
            <h3>Open vaults</h3>
            {state.sessions.map((vault) => <button className="block w-full break-words text-left" key={vault.id} disabled={navigation || vault.id === state.vault?.id}
              onClick={() => void controller.selectSession(vault.id)}>{vault.name}</button>)}
          </section>}
          {!sidebarCollapsed && <section className="sidebar-section sidebar-recents">
            <h3>Recent vaults</h3>
            {state.preferences.recent_vaults.map((entry) => <button className="block w-full break-all text-left text-xs" key={entry.vault_id}
              disabled={navigation} onClick={() => void controller.openRecent(entry)}>{entry.root_path}</button>)}
            {state.preferences.recent_vaults.length === 0 && <p className="text-xs text-neutral-500">No recent vaults</p>}
          </section>}
          <div className="sidebar-footer">
            <NavItem icon="folder" label="Open vault" ariaLabel="Open Vault" shortcut="O" disabled={navigation} onClick={() => setModal("vault")} />
            {state.vault && <NavItem icon="vault" label="Close vault" ariaLabel="Close Vault" disabled={navigation} onClick={() => void controller.closeVault()} />}
            <NavItem icon="quit" label="Quit" ariaLabel="Quit Page" disabled={state.pending !== null || state.quitting} onClick={() => void controller.requestQuit()} />
          </div>
        </aside>
        <div ref={split} className="workspace-split">
        <section className="workspace-main relative flex min-w-0 flex-1 flex-col" aria-label="Note workspace">
          <div className="document-tabbar">
            <div className="document-tab"><Icon name={openSource ? openSource.kind : "note"} size={15} />
              <span>{openSource ? openSource.relativePath.split("/").at(-1) : document?.path.split("/").at(-1) ?? "Workspace"}</span>
              {!viewing && isDirty(document) && <span className="tab-dirty" aria-label="Unsaved changes" />}
            </div>
          </div>
          {state.vault === null ? <div className="vault-welcome overflow-auto">
            <div className="welcome-mark"><Icon name="vault" size={36} /></div>
            <h2>Your notes, in your hands.</h2><p>Open a workspace or start a new one. Everything stays in your Markdown files.</p>
            <VaultForms controller={controller} state={state} />
          </div> : <>
            <div className="document-toolbar">
              <span className="document-breadcrumb"><span>{state.vault.name}</span><span className="breadcrumb-separator">/</span>{document?.path || "Select a note"}</span>
              <span role="status" className="save-state">{state.pending ? "Saving change…" : isDirty(document) ? "Unsaved changes" : readyDocument ? "Saved" : ""}</span>
              <button className="save-button" disabled={blocked || state.conflict !== null || !readyDocument || document.mixed || !isDirty(document)} onClick={() => void controller.save()}><Icon name="save" size={14} />Save</button>
              <button disabled={blocked || navigation || !readyDocument} onClick={() => noteAction("move")}>Rename / Move</button>
              <button disabled={blocked || navigation || !readyDocument} onClick={() => noteAction("delete")}>Delete Note</button>
            </div>
            {state.unknown && <section className="border-b bg-amber-50 p-3" role="alert">
              <p>The outcome of {state.unknown.attempt.operation} for {state.unknown.attempt.path} is unknown. Your draft is retained. Verify before making another change.</p>
              <button disabled={!backendReady(state) || state.unknown.verifying} onClick={() => void controller.verifyOutcome()}>Verify Outcome</button>
              {state.unknown.verifyError && <ErrorText error={state.unknown.verifyError} />}
            </section>}
            {state.recovery && <section className="border-b bg-amber-50 p-3" role="alert">
              <p>{state.recovery.error?.code === "metadata_sync_failed" ? "The filesystem changed, but metadata synchronization failed." : "This vault needs reconciliation."} Note changes are paused.</p>
              {state.recovery.details && <p className="break-all">{state.recovery.details.operation}: {state.recovery.details.relative_path}</p>}
              <button disabled={state.recovery.working || !backendReady(state)} onClick={() => void controller.reconcileRecovery()}>Reconcile</button>
              {state.recovery.details?.operation === "move" && <button disabled={state.recovery.working} onClick={() => setModal("failed-move")}>Confirm Failed Move</button>}
              {state.recovery.reconcileError && <ErrorText error={state.recovery.reconcileError} />}
            </section>}
            {document?.mixed && <p className="border-b bg-amber-50 p-3 text-sm">Mixed line endings: read-only until conversion is confirmed.
              <button disabled={blocked} onClick={() => setModal("convert")}>Convert to LF</button></p>}
            {document?.status === "orphaned" && <p role="alert" className="p-3">This note is missing on disk. Copy your draft from the editor, or <button disabled={blocked} onClick={() => setModal("orphan")}>Save Draft As New Note</button>.</p>}
            {document?.status === "loading" && <p className="p-6" role="status">Loading note…</p>}
            {document?.status === "unreadable" && <div className="p-6" role="alert">
              {document.loadError && <ErrorText error={document.loadError} />}
              <button disabled={!backendReady(state)} onClick={() => void controller.retryRead()}>Retry Read</button>
            </div>}
            {document && (document.status === "ready" || document.status === "orphaned") && <div className="min-h-0 flex-1 overflow-hidden">
              <MarkdownEditor documentKey={`${document.vaultId}:${document.noteId}:${document.editorKey}`} initialContent={document.draft}
                separator={document.mixed ? null : document.separator} readOnly={document.mixed} label={`Markdown: ${document.path}`}
                onChange={(content) => controller.setDraft(document.noteId, document.editorKey, content)} />
            </div>}
            {document === null && <div className="workspace-welcome">
              <div className="welcome-note"><Icon name="note" size={40} /></div>
              <h2>A little space to think.</h2><p>Select a note from the sidebar, or create one with Cmd/Ctrl+N.</p>
              <button disabled={blocked || navigation} onClick={() => noteAction("create")}>Create your first note</button>
            </div>}
            {viewing && openSource && <SourceViewer controller={controller} vaultId={state.vault.id} source={openSource} onClose={() => setOpenSource(null)} />}
            {document && <footer className="document-statusbar"><span>Markdown</span><span>{document.mixed ? "Mixed line endings" : describeSeparator(document.separator)} · UTF-8</span><span>{SHORTCUT}S to save · {SHORTCUT}K to ask</span></footer>}
            <AskBar controller={controller} state={state} onOpenSource={setOpenSource} />
          </>}
        </section>
        {searchVisible && state.vault && <SemanticSearch controller={controller} state={state} onClose={() => setSearchVisible(false)} onOpenSource={setOpenSource} />}
        {graphVisible && state.vault && <>
          <div className="split-handle" role="separator" aria-orientation="vertical" aria-label="Resize graph" tabIndex={0}
            onPointerDown={startResize} onKeyDown={resizeByKey} />
          <div className="graph-split" style={graphWidth === null ? undefined : { width: graphWidth, flexBasis: graphWidth }}>
            <Suspense fallback={<aside className="knowledge-panel graph-panel" role="status">Loading graph view…</aside>}>
              <KnowledgeGraph controller={controller} state={state} onClose={() => setGraphVisible(false)} />
            </Suspense>
          </div>
        </>}
        </div>
      </div>
    </>}
    {modal === "web" && <Dialog title="Add a Website" onCancel={cancel}>
      <WebPageForm onCancel={cancel} onSubmit={async (url) => { await controller.saveWebPage(url); cancel(); }} />
    </Dialog>}
    {modal === "vault" && <Dialog title="Choose a Vault" onCancel={cancel}>
      <VaultForms controller={controller} state={state} onDone={cancel} /><button onClick={cancel}>Cancel</button>
    </Dialog>}
    {(modal === "create" || modal === "move" || modal === "orphan") && <Dialog title={modal === "move" ? "Rename / Move Note" : "Create Note"} onCancel={cancel}>
      <NotePathForm initialPath={modal === "move" ? document?.path : ""} label={modal === "move" ? "Move Note" : "Create Note"} disabled={blocked}
        onCancel={cancel} onSubmit={async (path) => {
          const result = modal === "move" ? await controller.moveNote(path) : modal === "orphan" ? await controller.saveOrphanAs(path) : await controller.createNote(path);
          if (result) cancel();
          return result;
        }} />
      {state.actionError && <p role="alert"><ErrorText error={state.actionError.error} /></p>}
    </Dialog>}
    {modal === "delete" && <Dialog title="Permanently Delete Note" tone="danger" onCancel={cancel}>
      <p className="break-all">Delete {document?.path}? Deletion is permanent. There is no trash or undo.</p>
      <button disabled={blocked} onClick={() => void controller.deleteNote().then((done) => { if (done) cancel(); })}>Permanently Delete</button>
      <button disabled={state.pending !== null} onClick={cancel}>Cancel</button>
      {state.actionError && <p role="alert"><ErrorText error={state.actionError.error} /></p>}
    </Dialog>}
    {state.guard && <Dialog title="Unsaved Changes" onCancel={() => controller.guardCancel()}>
      <p className="mb-3">Save changes to {document?.path} before you {state.guard.label}?</p>
      <button disabled={state.guard.saving || blocked || document?.status === "orphaned"} onClick={() => void controller.guardSave()}>Save</button>
      <button disabled={state.guard.saving} onClick={() => void controller.guardDiscard()}>Discard</button>
      <button disabled={state.guard.saving} onClick={() => controller.guardCancel()}>Cancel</button>
    </Dialog>}
    {state.conflict && modal === null && <Dialog title="Changes on Disk" onCancel={() => controller.conflictKeepDraft()}>
      <p>Your draft is retained. The disk version is shown separately below.</p>
      {state.conflict.loading && <p role="status">Reading disk version…</p>}
      {state.conflict.fetchError && <p role="alert"><ErrorText error={state.conflict.fetchError} /></p>}
      {state.conflict.server && <pre className="my-3 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded border p-2" aria-label="Current disk content">{state.conflict.server.content}</pre>}
      <button disabled={!state.conflict.server} onClick={() => setModal("reload")}>Reload from Disk</button>
      <button disabled={!state.conflict.server || blocked} onClick={() => setModal("overwrite")}>Use My Draft</button>
      <button onClick={() => controller.conflictKeepDraft()}>Keep Draft</button>
    </Dialog>}
    {modal === "convert" && <Dialog title="Convert Line Endings" onCancel={cancel}>
      <p>Convert all line endings to LF? This changes the draft and requires an explicit save.</p>
      <button onClick={() => { controller.convertLineEndings(); cancel(); }}>Confirm Conversion</button><button onClick={cancel}>Cancel</button>
    </Dialog>}
    {modal === "reload" && <Dialog title="Discard Draft" onCancel={cancel}>
      <p>Reload from disk and discard your unsaved draft?</p>
      <button onClick={() => { controller.conflictReload(); cancel(); }}>Discard and Reload</button><button onClick={cancel}>Cancel</button>
    </Dialog>}
    {modal === "overwrite" && <Dialog title="Overwrite Disk Content" onCancel={cancel}>
      <p>Save your draft over the disk version you just read? Another intervening change can still cause a conflict.</p>
      <button disabled={blocked} onClick={() => { cancel(); void controller.conflictUseDraft(); }}>Confirm Overwrite</button><button onClick={cancel}>Cancel</button>
    </Dialog>}
    {modal === "failed-move" && <Dialog title="Confirm Reported Move" onCancel={cancel}>
      <p className="break-all">Confirm that note {state.recovery?.details?.note_id} moved to {state.recovery?.details?.relative_path}? Reconciliation will preserve its identity using only this reported move.</p>
      <button onClick={() => { cancel(); void controller.confirmFailedMove(); }}>Confirm and Reconcile</button><button onClick={cancel}>Cancel</button>
    </Dialog>}
    {modal === "reset" && <Dialog title="Reset Remembered Workspace" onCancel={cancel}>
      <p>Replace the preserved settings file with fresh workspace preferences? Note files are unchanged.</p>
      <button onClick={() => { cancel(); void controller.resetPreferences(); }}>Reset Preferences</button><button onClick={cancel}>Cancel</button>
    </Dialog>}
    {state.identity && <Dialog title="Different Vault Identity" onCancel={() => controller.rejectIdentity()}>
      <p className="break-all">The vault at {state.identity.vault.root_path} has a different identity from the remembered vault. Select this vault?</p>
      <button onClick={() => void controller.acceptIdentity()}>Select This Vault</button><button onClick={() => controller.rejectIdentity()}>Cancel</button>
    </Dialog>}
  </main>;
}
