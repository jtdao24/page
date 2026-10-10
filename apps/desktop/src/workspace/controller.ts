import type { PageClient } from "../core/client";
import type {
  BackendStatus,
  DesktopError,
  DesktopPreferences,
  NoteResponse,
  NoteSummaryResponse,
  ReconcileResponse,
  RecentVault,
  VaultResponse,
} from "../core/types";
import {
  MAX_RECENT_VAULTS,
  OUTCOME_UNKNOWN,
  emptyPreferences,
  isOutcomeUnknown,
  toDesktopError,
} from "../core/types";
import { type LineSeparator, convertToLf, detectLineEndings } from "./text";

export interface DocumentState {
  vaultId: string;
  noteId: string;
  path: string;
  /** loading: nothing of this note is shown yet; orphaned: deleted elsewhere, draft kept. */
  status: "loading" | "ready" | "unreadable" | "orphaned";
  /** The last full-note snapshot the server acknowledged. */
  accepted: NoteResponse | null;
  /** The serialized editor text. */
  draft: string;
  separator: LineSeparator;
  mixed: boolean;
  /** Changes whenever the editor must be recreated (identity, reload, conversion). */
  editorKey: number;
  loadError: DesktopError | null;
}

export type Operation = "create" | "update" | "move" | "delete";

/** A submitted mutation, kept so its outcome can be verified without replaying it. */
export interface Attempt {
  operation: Operation;
  vaultId: string;
  noteId: string | null;
  path: string;
  fromPath: string | null;
  content: string | null;
  baseRevision: string | null;
}

export interface MetadataSyncDetails {
  operation: string;
  relative_path: string;
  note_id: string | null;
}

export interface Recovery {
  vaultId: string;
  error: DesktopError | null;
  attempt: Attempt | null;
  details: MetadataSyncDetails | null;
  reconcileError: DesktopError | null;
  working: boolean;
}

export interface UnknownOutcome {
  attempt: Attempt;
  error: DesktopError;
  verifying: boolean;
  verifyError: DesktopError | null;
}

export interface Conflict {
  noteId: string;
  error: DesktopError | null;
  server: NoteResponse | null;
  loading: boolean;
  fetchError: DesktopError | null;
}

export interface Guard {
  label: string;
  saving: boolean;
}

export interface IdentityMismatch {
  remembered: RecentVault;
  vault: VaultResponse;
}

export interface Message {
  tone: "info" | "error";
  text: string;
}

export interface WorkspaceState {
  phase: "unavailable" | "initializing" | "active";
  backend: BackendStatus | null;
  backendError: DesktopError | null;
  preferences: DesktopPreferences;
  preferencesWarning: DesktopError | null;
  preferencesWriteError: DesktopError | null;
  vault: VaultResponse | null;
  sessions: VaultResponse[];
  vaultBusy: boolean;
  vaultError: DesktopError | null;
  notes: NoteSummaryResponse[] | null;
  notesLoading: boolean;
  listError: DesktopError | null;
  document: DocumentState | null;
  pending: (Attempt & { id: number }) | null;
  actionError: { operation: Operation; error: DesktopError } | null;
  conflict: Conflict | null;
  recovery: Recovery | null;
  unknown: UnknownOutcome | null;
  guard: Guard | null;
  identity: IdentityMismatch | null;
  lastReconcile: ReconcileResponse | null;
  message: Message | null;
  quitting: boolean;
}

export function isDirty(document: DocumentState | null): boolean {
  if (document === null || document.accepted === null) return false;
  if (document.status === "orphaned") return true;
  return document.status === "ready" && document.draft !== document.accepted.content;
}

export function backendReady(state: WorkspaceState): boolean {
  return state.backend?.state === "ready";
}

/** Note mutations need a ready backend and no outstanding or unresolved work. */
export function mutationsBlocked(state: WorkspaceState): boolean {
  return (
    !backendReady(state) ||
    state.vault === null ||
    state.pending !== null ||
    state.unknown !== null ||
    state.recovery !== null ||
    state.vaultBusy ||
    state.quitting
  );
}

/** Navigation and destructive actions wait for an outstanding mutation. */
export function navigationBlocked(state: WorkspaceState): boolean {
  return state.pending !== null || state.unknown !== null || state.quitting || state.vaultBusy || !backendReady(state);
}

function initialState(available: boolean): WorkspaceState {
  return {
    phase: available ? "initializing" : "unavailable",
    backend: null,
    backendError: null,
    preferences: emptyPreferences(),
    preferencesWarning: null,
    preferencesWriteError: null,
    vault: null,
    sessions: [],
    vaultBusy: false,
    vaultError: null,
    notes: null,
    notesLoading: false,
    listError: null,
    document: null,
    pending: null,
    actionError: null,
    conflict: null,
    recovery: null,
    unknown: null,
    guard: null,
    identity: null,
    lastReconcile: null,
    message: null,
    quitting: false,
  };
}

function localError(code: string, message: string): DesktopError {
  return { kind: "backend", status: null, code, message, details: null };
}

function syncDetails(error: DesktopError): MetadataSyncDetails | null {
  const details = error.details;
  if (details === null) return null;
  const { operation, relative_path: path, note_id: noteId } = details;
  if (typeof operation !== "string" || typeof path !== "string") return null;
  if (noteId !== null && typeof noteId !== "string") return null;
  return { operation, relative_path: path, note_id: noteId };
}

function upsert(sessions: VaultResponse[], vault: VaultResponse): VaultResponse[] {
  return [...sessions.filter((session) => session.id !== vault.id), vault].sort((left, right) =>
    left.root_path < right.root_path ? -1 : left.root_path > right.root_path ? 1 : 0,
  );
}

interface Ticket {
  generation: number;
  vault: number;
  document: number;
}

interface GuardHandlers {
  proceed: () => Promise<void>;
  cancel: () => void;
}

/**
 * Owns all workspace state and orchestrates every asynchronous action.
 *
 * Each request captures a ticket (backend generation, vault epoch, document
 * epoch). Success and error callbacks check it before touching state, so a
 * slow result for an old note, vault or connection is ignored. Abandoning a
 * result never cancels the storage work in Page Core.
 */
export class WorkspaceController {
  private state: WorkspaceState;
  private readonly listeners = new Set<() => void>();
  private vaultEpoch = 0;
  private documentEpoch = 0;
  private editorKeys = 0;
  private mutationIds = 0;
  private listRequests = 0;
  private backendRequests = 0;
  private restarting = false;
  private quitRequested = false;
  private readonly mutationJobs = new Set<Promise<unknown>>();
  private started = false;
  private guardHandlers: GuardHandlers | null = null;
  private preferenceWrites: Promise<void> = Promise.resolve();
  private readonly client: PageClient | null;

  constructor(client: PageClient | null) {
    this.client = client;
    this.state = initialState(client !== null);
  }

  getState = (): WorkspaceState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  private set(patch: Partial<WorkspaceState>): void {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) listener();
  }

  private updateDocument(patch: Partial<DocumentState>): void {
    if (this.state.document !== null) this.set({ document: { ...this.state.document, ...patch } });
  }

  private announce(text: string, tone: Message["tone"] = "info"): void {
    this.set({ message: { tone, text } });
  }

  dismissMessage(): void {
    this.set({ message: null });
  }

  private get api(): PageClient {
    if (this.client === null) throw new Error("desktop runtime unavailable");
    return this.client;
  }

  private ticket(): Ticket {
    return {
      generation: this.state.backend?.generation ?? 0,
      vault: this.vaultEpoch,
      document: this.documentEpoch,
    };
  }

  private owns(ticket: Ticket, scope: "vault" | "document"): boolean {
    const generation = this.state.backend?.generation ?? 0;
    if (ticket.generation !== generation || ticket.vault !== this.vaultEpoch) return false;
    return scope === "vault" || ticket.document === this.documentEpoch;
  }

  // --- Lifecycle -----------------------------------------------------------

  /** Subscribe to backend and quit events; returns the cleanup function. */
  attach(): () => void {
    if (this.client === null) return () => {};
    let active = true;
    const cleanups: (() => void)[] = [];
    const keep = (subscription: Promise<() => void>) => {
      void subscription.then(
        (unlisten) => (active ? cleanups.push(unlisten) : unlisten()),
        () => {},
      );
    };
    keep(this.client.onBackendStatus((status) => this.applyStatus(status)));
    keep(this.client.onQuitRequested(() => void this.requestQuit()));
    return () => {
      active = false;
      for (const cleanup of cleanups.splice(0)) cleanup();
    };
  }

  /** Read preferences, start Core and restore the remembered workspace, once. */
  async start(): Promise<void> {
    if (this.started || this.client === null) return;
    this.started = true;
    let preferences = emptyPreferences();
    try {
      preferences = await this.api.preferencesRead();
      this.set({ preferences });
    } catch (error) {
      this.set({ preferencesWarning: toDesktopError(error) });
    }
    const ready = await this.startBackend();
    this.set({ phase: "active" });
    if (ready) await this.restore(preferences);
  }

  private applyStatus(status: BackendStatus): void {
    const current = this.state.backend;
    if (current !== null && status.generation < current.generation) return;
    if (status.state === "failed" && this.state.pending !== null) {
      const { id: _id, ...attempt } = this.state.pending;
      void _id;
      this.set({ pending: null, unknown: {
        attempt, error: localError(OUTCOME_UNKNOWN, "Page Core stopped during a change; its outcome is unknown."),
        verifying: false, verifyError: null,
      } });
    }
    this.set({ backend: status, backendError: status.error });
  }

  private async startBackend(): Promise<boolean> {
    const request = ++this.backendRequests;
    try {
      const status = await this.api.backendStart();
      if (request !== this.backendRequests) return false;
      this.applyStatus(status);
      return backendReady(this.state);
    } catch (error) {
      if (request !== this.backendRequests) return false;
      this.set({ backendError: toDesktopError(error) });
      try {
        const status = await this.api.backendStatus();
        if (request === this.backendRequests) this.applyStatus(status);
      } catch {
        // The start error is already shown.
      }
      return false;
    }
  }

  async retryStart(): Promise<void> {
    if (this.client === null || this.state.quitting || this.restarting) return;
    if (!(await this.startBackend())) return;
    if (this.state.vault === null) {
      await this.restore(this.state.preferences);
      return;
    }
    // Core sessions belong to one process: a new process after a crash has
    // never opened the active vault, so reopen it as restart() does.
    this.vaultEpoch += 1;
    this.set({ sessions: [], conflict: null });
    await this.reopenActiveVault();
  }

  private async restore(preferences: DesktopPreferences): Promise<void> {
    const entry = preferences.recent_vaults.find((item) => item.vault_id === preferences.active_vault_id);
    if (entry === undefined || this.state.vault !== null) return;
    await this.openEntry(entry, entry.last_note_id);
  }

  /** Restart Core: drafts stay in memory; interrupted mutations become uncertain. */
  async restart(): Promise<void> {
    if (this.client === null || this.state.quitting || this.restarting) return;
    this.restarting = true;
    const backendRequest = ++this.backendRequests;
    try {
      const pending = this.state.pending;
      if (pending !== null) {
        const { id: _id, ...attempt } = pending;
        void _id;
        this.set({
          pending: null,
          unknown: {
            attempt,
            error: localError(OUTCOME_UNKNOWN, "Page Core restarted while this change was in progress; it may or may not have been saved."),
            verifying: false,
            verifyError: null,
          },
        });
      }
      this.vaultEpoch += 1;
      this.set({ backendError: null, sessions: [], conflict: null });
      try {
        const status = await this.api.backendRestart();
        if (backendRequest !== this.backendRequests) return;
        this.applyStatus(status);
      } catch (error) {
        this.set({ backendError: toDesktopError(error) });
        return;
      }
      await this.reopenActiveVault();
    } finally {
      this.restarting = false;
    }
  }

  /** Reopen the active vault in a freshly started Core process. */
  private async reopenActiveVault(): Promise<void> {
    const vault = this.state.vault;
    if (vault === null) return;
    const ticket = this.ticket();
    this.set({ vaultBusy: true });
    try {
      const reopened = await this.api.vaultOpen(vault.root_path);
      if (!this.owns(ticket, "vault")) return;
      if (reopened.id !== vault.id) {
        this.set({
          identity: { remembered: { vault_id: vault.id, root_path: vault.root_path, last_note_id: null }, vault: reopened },
        });
        return;
      }
      this.set({ vault: reopened, sessions: [reopened] });
      if (reopened.needs_reconciliation) {
        this.enterRecovery(null, null);
        return;
      }
      const notes = await this.loadNotes();
      if (notes !== null && this.owns(ticket, "vault")) await this.refreshDocument(notes);
    } catch (error) {
      if (this.owns(ticket, "vault")) this.set({ vaultError: toDesktopError(error) });
    } finally {
      if (this.owns(ticket, "vault")) this.set({ vaultBusy: false });
    }
  }

  // --- Dirty-document guard ------------------------------------------------

  /**
   * Run `action` now if the document is clean, or after the user saves or
   * discards. Resolves to undefined when the user cancels.
   */
  guarded<T>(label: string, action: () => Promise<T> | T): Promise<T | undefined> {
    if (!isDirty(this.state.document)) return Promise.resolve(action());
    if (this.state.guard !== null) return Promise.resolve(undefined);
    return new Promise((resolve) => {
      this.guardHandlers = {
        proceed: async () => resolve(await action()),
        cancel: () => resolve(undefined),
      };
      this.set({ guard: { label, saving: false } });
    });
  }

  async guardSave(): Promise<void> {
    const handlers = this.guardHandlers;
    if (handlers === null || this.state.guard === null || this.state.guard.saving) return;
    this.set({ guard: { ...this.state.guard, saving: true } });
    const saved = await this.save();
    this.guardHandlers = null;
    this.set({ guard: null });
    if (saved && !isDirty(this.state.document)) {
      await handlers.proceed();
    } else {
      handlers.cancel();
      if (this.state.message === null || this.state.message.tone !== "error") {
        this.announce("The note was not fully saved, so the action did not continue.", "error");
      }
    }
  }

  async guardDiscard(): Promise<void> {
    const handlers = this.guardHandlers;
    if (handlers === null || this.state.guard?.saving) return;
    this.guardHandlers = null;
    this.discardDraft();
    this.set({ guard: null });
    await handlers.proceed();
  }

  guardCancel(): void {
    if (this.state.guard?.saving) return;
    const handlers = this.guardHandlers;
    this.guardHandlers = null;
    this.set({ guard: null });
    handlers?.cancel();
  }

  /** Memory only: never writes. */
  private discardDraft(): void {
    const document = this.state.document;
    if (document === null) return;
    if (document.status === "orphaned" || document.accepted === null) {
      this.documentEpoch += 1;
      this.set({ document: null, conflict: null });
      return;
    }
    const lineEndings = detectLineEndings(document.accepted.content);
    this.updateDocument({
      draft: document.accepted.content,
      separator: lineEndings.separator,
      mixed: lineEndings.mixed,
      editorKey: (this.editorKeys += 1),
    });
    this.set({ conflict: null });
  }

  // --- Preferences ---------------------------------------------------------

  private writePreferences(preferences: DesktopPreferences): void {
    this.set({ preferences });
    // A problematic settings file is preserved until an explicit reset.
    if (this.state.preferencesWarning !== null) return;
    this.queuePreferenceWrite(preferences);
  }

  private queuePreferenceWrite(preferences: DesktopPreferences): void {
    // Writes are issued strictly in order, so an older selection never
    // replaces a newer one.
    this.preferenceWrites = this.preferenceWrites.then(async () => {
      try {
        await this.api.preferencesWrite(preferences);
        this.set({ preferencesWriteError: null });
      } catch (error) {
        this.set({ preferencesWriteError: toDesktopError(error) });
      }
    });
  }

  private remember(vault: VaultResponse, noteId: string | null | undefined): void {
    const current = this.state.preferences;
    const previous = current.recent_vaults.find((entry) => entry.vault_id === vault.id);
    const entry: RecentVault = {
      vault_id: vault.id,
      root_path: vault.root_path,
      last_note_id: noteId === undefined ? (previous?.last_note_id ?? null) : noteId,
    };
    const recent = [
      entry,
      ...current.recent_vaults.filter(
        (item) => item.vault_id !== vault.id && item.root_path !== vault.root_path,
      ),
    ].slice(0, MAX_RECENT_VAULTS);
    this.writePreferences({ version: 1, recent_vaults: recent, active_vault_id: vault.id });
  }

  async resetPreferences(): Promise<void> {
    const vault = this.state.vault;
    const fresh = emptyPreferences();
    if (vault !== null) {
      fresh.recent_vaults = [{ vault_id: vault.id, root_path: vault.root_path, last_note_id: this.state.document?.noteId ?? null }];
      fresh.active_vault_id = vault.id;
    }
    this.set({ preferencesWarning: null, preferences: fresh });
    this.queuePreferenceWrite(fresh);
    await this.preferenceWrites;
  }

  /** Resolves once queued preference writes have finished (tests and quit). */
  flushPreferences(): Promise<void> {
    return this.preferenceWrites;
  }

  // --- Vaults --------------------------------------------------------------

  createVault(rootPath: string, name: string): Promise<boolean | undefined> {
    return this.guarded("create a vault", () =>
      this.vaultAction(() => this.api.vaultCreate(rootPath, name), null),
    );
  }

  openVault(rootPath: string): Promise<boolean | undefined> {
    return this.guarded("open a vault", () => this.vaultAction(() => this.api.vaultOpen(rootPath), null));
  }

  openRecent(entry: RecentVault): Promise<boolean | undefined> {
    return this.guarded("open another vault", () => this.openEntry(entry, null));
  }

  /** Switch to an already open session. */
  selectSession(vaultId: string): Promise<boolean | undefined> {
    return this.guarded("switch vaults", () => this.vaultAction(() => this.api.vaultGet(vaultId), null));
  }

  private async openEntry(entry: RecentVault, restoreNoteId: string | null): Promise<boolean> {
    return this.vaultAction(() => this.api.vaultOpen(entry.root_path), restoreNoteId, entry);
  }

  private async vaultAction(
    request: () => Promise<VaultResponse>,
    restoreNoteId: string | null,
    remembered?: RecentVault,
  ): Promise<boolean> {
    if (this.client === null || navigationBlocked(this.state)) return false;
    this.vaultEpoch += 1;
    const ticket = this.ticket();
    this.set({ vaultBusy: true, vaultError: null });
    try {
      const vault = await request();
      if (!this.owns(ticket, "vault")) return false;
      this.set({ vaultBusy: false });
      if (remembered !== undefined && vault.id !== remembered.vault_id) {
        // Never treat another manifest identity as the remembered vault silently.
        this.set({ identity: { remembered, vault }, sessions: upsert(this.state.sessions, vault) });
        return false;
      }
      await this.activate(vault, restoreNoteId);
      return true;
    } catch (error) {
      if (!this.owns(ticket, "vault")) return false;
      this.set({ vaultBusy: false, vaultError: toDesktopError(error) });
      return false;
    }
  }

  async acceptIdentity(): Promise<void> {
    const identity = this.state.identity;
    if (identity === null) return;
    this.set({ identity: null });
    await this.activate(identity.vault, null);
  }

  rejectIdentity(): void {
    this.set({ identity: null });
    this.announce("The vault at that folder has a different identity and was not selected.");
  }

  private async activate(vault: VaultResponse, restoreNoteId: string | null): Promise<void> {
    this.vaultEpoch += 1;
    this.documentEpoch += 1;
    const ticket = this.ticket();
    this.set({
      vault,
      sessions: upsert(this.state.sessions, vault),
      notes: null,
      document: null,
      listError: null,
      vaultError: null,
      conflict: null,
      recovery: null,
      actionError: null,
      lastReconcile: null,
    });
    this.remember(vault, undefined);
    if (vault.needs_reconciliation) {
      this.enterRecovery(null, null);
      return;
    }
    const notes = await this.loadNotes();
    if (notes === null || !this.owns(ticket, "vault") || restoreNoteId === null) return;
    if (notes.some((note) => note.id === restoreNoteId)) {
      await this.openNote(restoreNoteId);
    } else {
      // A remembered note that no longer exists clears the selection.
      this.remember(vault, null);
    }
  }

  closeVault(): Promise<boolean | undefined> {
    return this.guarded("close the vault", async () => {
      const vault = this.state.vault;
      if (vault === null || navigationBlocked(this.state)) return false;
      const ticket = this.ticket();
      this.set({ vaultBusy: true, vaultError: null });
      try {
        await this.api.vaultClose(vault.id);
      } catch (error) {
        if (this.owns(ticket, "vault")) this.set({ vaultBusy: false, vaultError: toDesktopError(error) });
        return false;
      }
      if (!this.owns(ticket, "vault")) return false;
      this.vaultEpoch += 1;
      this.documentEpoch += 1;
      this.set({
        vaultBusy: false,
        vault: null,
        sessions: this.state.sessions.filter((session) => session.id !== vault.id),
        notes: null,
        document: null,
        conflict: null,
        recovery: null,
        unknown: null,
        listError: null,
        lastReconcile: null,
      });
      this.writePreferences({ ...this.state.preferences, active_vault_id: null });
      this.announce(`Closed ${vault.name}. Its files were not changed.`);
      return true;
    });
  }

  // --- Notes ---------------------------------------------------------------

  private async loadNotes(): Promise<NoteSummaryResponse[] | null> {
    const vault = this.state.vault;
    if (vault === null) return null;
    const ticket = this.ticket();
    const request = ++this.listRequests;
    this.set({ notesLoading: true });
    try {
      const notes = await this.api.noteList(vault.id);
      if (!this.owns(ticket, "vault") || request !== this.listRequests) return null;
      this.set({ notes, notesLoading: false, listError: null });
      return notes;
    } catch (error) {
      if (!this.owns(ticket, "vault") || request !== this.listRequests) return null;
      const failure = toDesktopError(error);
      this.set({ notesLoading: false, listError: failure });
      if (failure.code === "reconciliation_required") this.enterRecovery(null, failure);
      return null;
    }
  }

  /** Explicit retry of a failed list. */
  async reloadNotes(): Promise<void> {
    await this.loadNotes();
  }

  /** Graph reads share the protected bridge; the graph view owns response lifetimes. */
  searchVault(vaultId: string, query: string, limit = 10) {
    return this.api.semanticSearch(vaultId, query, limit);
  }

  /** Grounded question answering; the Ask panel owns response lifetimes. */
  askVault(vaultId: string, question: string, budget: number) {
    return this.api.askQuestion(vaultId, question, budget);
  }

  geminiKeyStatus() {
    return this.api.geminiKeyStatus();
  }

  /** Save or remove the stored key, then restart Core so it takes effect. */
  async setGeminiKey(key: string | null): Promise<void> {
    if (key === null) await this.api.geminiKeyClear();
    else await this.api.geminiKeySave(key);
    await this.restart();
  }

  indexVault(vaultId: string, rebuild = false) {
    return this.api.semanticIndex(vaultId, rebuild);
  }

  readGraph(vaultId: string) {
    return this.api.graphRead(vaultId);
  }

  selectNote(noteId: string): Promise<void | undefined> {
    if (navigationBlocked(this.state) || this.state.document?.noteId === noteId) return Promise.resolve(undefined);
    return this.guarded("open another note", () => this.openNote(noteId));
  }

  /** Explicit retry of a failed read. */
  async retryRead(): Promise<void> {
    const document = this.state.document;
    if (document !== null && document.status === "unreadable") await this.openNote(document.noteId);
  }

  private documentFrom(note: NoteResponse): DocumentState {
    const lineEndings = detectLineEndings(note.content);
    return {
      vaultId: note.vault_id,
      noteId: note.id,
      path: note.relative_path,
      status: "ready",
      accepted: note,
      draft: note.content,
      separator: lineEndings.separator,
      mixed: lineEndings.mixed,
      editorKey: (this.editorKeys += 1),
      loadError: null,
    };
  }

  private async openNote(noteId: string): Promise<void> {
    const vault = this.state.vault;
    if (vault === null) return;
    this.documentEpoch += 1;
    const ticket = this.ticket();
    const summary = this.state.notes?.find((note) => note.id === noteId);
    this.set({
      conflict: null,
      actionError: null,
      document: {
        vaultId: vault.id,
        noteId,
        path: summary?.relative_path ?? "",
        status: "loading",
        accepted: null,
        draft: "",
        separator: "\n",
        mixed: false,
        editorKey: (this.editorKeys += 1),
        loadError: null,
      },
    });
    try {
      const note = await this.api.noteRead(vault.id, noteId);
      if (!this.owns(ticket, "document")) return;
      this.set({ document: this.documentFrom(note) });
      this.remember(vault, noteId);
    } catch (error) {
      if (!this.owns(ticket, "document")) return;
      const failure = toDesktopError(error);
      this.updateDocument({ status: "unreadable", loadError: failure });
      if (failure.code === "reconciliation_required") this.enterRecovery(null, failure);
    }
  }

  /** Called by the editor with its serialized text. */
  setDraft(noteId: string, editorKey: number, text: string): void {
    const document = this.state.document;
    if (
      document === null ||
      document.noteId !== noteId ||
      document.editorKey !== editorKey ||
      document.mixed ||
      (document.status !== "ready" && document.status !== "orphaned")
    ) {
      return;
    }
    if (document.draft !== text) this.updateDocument({ draft: text });
  }

  /** Confirmed conversion of mixed separators to LF; marks the draft dirty, never saves. */
  convertLineEndings(): void {
    const document = this.state.document;
    if (document === null || !document.mixed || document.status !== "ready") return;
    this.updateDocument({
      draft: convertToLf(document.draft),
      separator: "\n",
      mixed: false,
      editorKey: (this.editorKeys += 1),
    });
  }

  private beginMutation(attempt: Attempt): number {
    const id = (this.mutationIds += 1);
    this.set({ pending: { ...attempt, id }, actionError: null, message: null });
    return id;
  }

  /** True when this mutation still owns the workspace (not abandoned by a restart). */
  private endMutation(id: number): boolean {
    if (this.state.pending?.id !== id) return false;
    this.set({ pending: null });
    return true;
  }

  private async mutate<T>(attempt: Attempt, request: () => Promise<T>): Promise<T | null> {
    if (this.client === null || mutationsBlocked(this.state)) return null;
    const id = this.beginMutation(attempt);
    try {
      const result = await request();
      return this.endMutation(id) ? result : null;
    } catch (error) {
      if (this.endMutation(id)) this.mutationFailed(attempt, toDesktopError(error));
      return null;
    }
  }

  private mutationFailed(attempt: Attempt, error: DesktopError): void {
    if (isOutcomeUnknown(error)) {
      this.set({ unknown: { attempt, error, verifying: false, verifyError: null } });
    } else if (error.code === "metadata_sync_failed") {
      this.enterRecovery(attempt, error);
    } else if (error.code === "reconciliation_required") {
      this.enterRecovery(null, error);
    } else if (attempt.noteId !== null && (error.code === "revision_conflict" || error.code === "note_conflict")) {
      void this.openConflict(attempt.noteId ?? "", error);
    } else if (attempt.noteId !== null && error.code === "note_not_found") {
      this.orphan();
    } else {
      this.set({ actionError: { operation: attempt.operation, error } });
    }
  }

  /** Save the draft. Resolves true only when the submitted draft is acknowledged and still current. */
  save(): Promise<boolean> {
    return this.trackMutation(() => this.submitUpdate(null));
  }

  private trackMutation<T>(action: () => Promise<T>): Promise<T> {
    const job = action();
    this.mutationJobs.add(job);
    void job.finally(() => this.mutationJobs.delete(job)).catch(() => {});
    return job;
  }

  private async submitUpdate(revisionOverride: string | null): Promise<boolean> {
    if (revisionOverride === null && this.state.conflict !== null) return false;
    const document = this.state.document;
    if (document === null || document.status !== "ready" || document.mixed || document.accepted === null) {
      return false;
    }
    if (!isDirty(document) && revisionOverride === null) return true;
    const attempt: Attempt = {
      operation: "update",
      vaultId: document.vaultId,
      noteId: document.noteId,
      path: document.accepted.relative_path,
      fromPath: null,
      content: document.draft,
      baseRevision: revisionOverride ?? document.accepted.revision,
    };
    const content = document.draft;
    const revision = attempt.baseRevision ?? "";
    const note = await this.mutate(attempt, () =>
      this.api.noteUpdate(document.vaultId, document.noteId, revision, content),
    );
    if (note === null) return false;
    this.acknowledge(note);
    this.set({ conflict: null });
    this.announce(`Saved ${note.relative_path}.`);
    void this.loadNotes();
    return !isDirty(this.state.document);
  }

  /** Accept a server snapshot for the current note; later typing stays dirty. */
  private acknowledge(note: NoteResponse): void {
    const document = this.state.document;
    if (document === null || document.noteId !== note.id || document.vaultId !== note.vault_id) return;
    this.updateDocument({ accepted: note, path: note.relative_path, status: "ready" });
  }

  createNote(relativePath: string): Promise<boolean> {
    return this.trackMutation(() => this.createWith(relativePath, ""));
  }

  /** Create a new note from an orphaned draft at a user-chosen path. */
  saveOrphanAs(relativePath: string): Promise<boolean> {
    const document = this.state.document;
    if (document === null || document.status !== "orphaned") return Promise.resolve(false);
    return this.trackMutation(() => this.createWith(relativePath, document.draft));
  }

  private async createWith(relativePath: string, content: string): Promise<boolean> {
    const vault = this.state.vault;
    if (vault === null) return false;
    const attempt: Attempt = {
      operation: "create",
      vaultId: vault.id,
      noteId: null,
      path: relativePath,
      fromPath: null,
      content,
      baseRevision: null,
    };
    const note = await this.mutate(attempt, () => this.api.noteCreate(vault.id, relativePath, content));
    if (note === null) return false;
    this.documentEpoch += 1;
    this.set({ document: this.documentFrom(note), conflict: null });
    this.remember(vault, note.id);
    this.announce(`Created ${note.relative_path}.`);
    void this.loadNotes();
    return true;
  }

  moveNote(relativePath: string): Promise<boolean> {
    return this.trackMutation(() => this.submitMove(relativePath));
  }

  private async submitMove(relativePath: string): Promise<boolean> {
    const document = this.state.document;
    if (document === null || document.status !== "ready" || document.accepted === null) return false;
    const accepted = document.accepted;
    const attempt: Attempt = {
      operation: "move",
      vaultId: document.vaultId,
      noteId: document.noteId,
      path: relativePath,
      fromPath: accepted.relative_path,
      content: null,
      baseRevision: accepted.revision,
    };
    const note = await this.mutate(attempt, () =>
      this.api.noteMove(document.vaultId, document.noteId, accepted.revision, relativePath),
    );
    if (note === null) return false;
    this.acknowledge(note);
    this.announce(`Moved to ${note.relative_path}.`);
    void this.loadNotes();
    return true;
  }

  deleteNote(): Promise<boolean> {
    return this.trackMutation(() => this.submitDelete());
  }

  private async submitDelete(): Promise<boolean> {
    const document = this.state.document;
    const vault = this.state.vault;
    if (vault === null || document === null || document.status !== "ready" || document.accepted === null) return false;
    const accepted = document.accepted;
    const attempt: Attempt = {
      operation: "delete",
      vaultId: document.vaultId,
      noteId: document.noteId,
      path: accepted.relative_path,
      fromPath: null,
      content: null,
      baseRevision: accepted.revision,
    };
    const done = await this.mutate(attempt, async () => {
      await this.api.noteDelete(document.vaultId, document.noteId, accepted.revision);
      return true;
    });
    if (done === null) return false;
    if (this.state.document?.noteId === document.noteId) {
      this.documentEpoch += 1;
      this.set({ document: null });
    }
    this.remember(vault, null);
    this.announce(`Permanently deleted ${accepted.relative_path}.`);
    void this.loadNotes();
    return true;
  }

  // --- Conflicts and orphans -----------------------------------------------

  private async openConflict(noteId: string, error: DesktopError | null): Promise<void> {
    const vault = this.state.vault;
    if (vault === null) return;
    const ticket = this.ticket();
    this.set({ conflict: { noteId, error, server: null, loading: true, fetchError: null } });
    try {
      const server = await this.api.noteRead(vault.id, noteId);
      if (!this.owns(ticket, "document") || this.state.conflict?.noteId !== noteId) return;
      this.set({ conflict: { noteId, error, server, loading: false, fetchError: null } });
    } catch (failure) {
      if (!this.owns(ticket, "document") || this.state.conflict?.noteId !== noteId) return;
      const fetchError = toDesktopError(failure);
      if (fetchError.code === "note_not_found") {
        this.set({ conflict: null });
        this.orphan();
      } else {
        this.set({ conflict: { noteId, error, server: null, loading: false, fetchError } });
      }
    }
  }

  /** Close the comparison; the draft and its prior accepted revision stay. */
  conflictKeepDraft(): void {
    this.set({ conflict: null });
  }

  /** After a confirmed discard warning: replace the draft with the disk version. */
  conflictReload(): void {
    const server = this.state.conflict?.server;
    if (server === undefined || server === null) return;
    this.set({ document: this.documentFrom(server), conflict: null });
  }

  /** After confirmed overwrite: one explicit save against the freshly read revision. */
  async conflictUseDraft(): Promise<boolean> {
    const server = this.state.conflict?.server;
    if (server === undefined || server === null) return false;
    this.set({ conflict: null });
    return this.trackMutation(() => this.submitUpdate(server.revision));
  }

  private orphan(): void {
    const document = this.state.document;
    if (document === null || document.accepted === null) return;
    this.updateDocument({ status: "orphaned" });
    this.announce("This note no longer exists on disk. Your unsaved text is kept here only in memory.", "error");
  }

  // --- Reconciliation and recovery -----------------------------------------

  private enterRecovery(attempt: Attempt | null, error: DesktopError | null): void {
    const vault = this.state.vault;
    if (vault === null) return;
    this.set({
      vault: { ...vault, needs_reconciliation: true },
      recovery: {
        vaultId: vault.id,
        error,
        attempt,
        details: error !== null && error.code === "metadata_sync_failed" ? syncDetails(error) : null,
        reconcileError: null,
        working: false,
      },
    });
  }

  reconcileRecovery(): Promise<void> {
    return this.runRecovery({});
  }

  /** After explicit confirmation: tell reconciliation about the reported failed move only. */
  confirmFailedMove(): Promise<void> {
    const details = this.state.recovery?.details;
    if (details === null || details === undefined || details.operation !== "move" || details.note_id === null) {
      return Promise.resolve();
    }
    return this.runRecovery({ [details.note_id]: details.relative_path });
  }

  private async runRecovery(knownRenames: Record<string, string>): Promise<void> {
    const recovery = this.state.recovery;
    const vault = this.state.vault;
    if (recovery === null || vault === null || recovery.working || !backendReady(this.state)) return;
    const ticket = this.ticket();
    this.set({ recovery: { ...recovery, working: true, reconcileError: null } });
    try {
      const counts = await this.api.vaultReconcile(vault.id, knownRenames);
      if (!this.owns(ticket, "vault")) return;
      const fresh = await this.api.vaultGet(vault.id);
      if (!this.owns(ticket, "vault")) return;
      this.set({ vault: fresh, sessions: upsert(this.state.sessions, fresh), lastReconcile: counts });
      const notes = await this.loadNotes();
      if (!this.owns(ticket, "vault")) return;
      if (notes === null) {
        this.set({ recovery: { ...recovery, working: false, reconcileError: this.state.listError } });
        return;
      }
      if (recovery.attempt !== null) {
        this.announce(await this.observe(recovery.attempt, notes));
      } else {
        await this.refreshDocument(notes);
        this.announce("Reconciliation finished.");
      }
      if (this.owns(ticket, "vault")) this.set({ recovery: null });
    } catch (error) {
      if (!this.owns(ticket, "vault")) return;
      this.set({ recovery: { ...recovery, working: false, reconcileError: toDesktopError(error) } });
    }
  }

  /** Reconcile external changes, then list notes. Dirty drafts are never rebased silently. */
  async refreshFromDisk(): Promise<void> {
    const vault = this.state.vault;
    if (vault === null || mutationsBlocked(this.state)) return;
    const ticket = this.ticket();
    this.set({ vaultBusy: true, listError: null });
    try {
      const counts = await this.api.vaultReconcile(vault.id, {});
      if (!this.owns(ticket, "vault")) return;
      this.set({ lastReconcile: counts, vaultBusy: false });
      this.announce(
        `Refreshed: ${counts.added} added, ${counts.modified} modified, ${counts.renamed} renamed, ${counts.missing} missing, ${counts.unchanged} unchanged.`,
      );
      const notes = await this.loadNotes();
      if (notes !== null && this.owns(ticket, "vault")) await this.refreshDocument(notes);
    } catch (error) {
      if (!this.owns(ticket, "vault")) return;
      const failure = toDesktopError(error);
      this.set({ vaultBusy: false, listError: failure });
      if (failure.code === "reconciliation_required") this.enterRecovery(null, failure);
    }
  }

  private async refreshDocument(notes: NoteSummaryResponse[]): Promise<void> {
    const document = this.state.document;
    const vault = this.state.vault;
    if (document === null || vault === null) return;
    const summary = notes.find((note) => note.id === document.noteId);
    if (summary === undefined) {
      if (document.status === "orphaned") return;
      if (isDirty(document)) {
        this.orphan();
      } else {
        this.documentEpoch += 1;
        this.set({ document: null });
        this.remember(vault, null);
        this.announce(`${document.path || "The selected note"} no longer exists.`);
      }
      return;
    }
    if (document.status === "loading" || document.status === "unreadable") {
      await this.openNote(document.noteId);
      return;
    }
    if (document.status !== "ready" || document.accepted === null) return;
    if (summary.revision === document.accepted.revision) return;
    if (isDirty(document)) {
      await this.openConflict(document.noteId, null);
      return;
    }
    const ticket = this.ticket();
    try {
      const note = await this.api.noteRead(vault.id, document.noteId);
      if (this.owns(ticket, "document")) {
        if (isDirty(this.state.document)) await this.openConflict(note.id, null);
        else this.set({ document: this.documentFrom(note) });
      }
    } catch (error) {
      if (!this.owns(ticket, "document")) return;
      const failure = toDesktopError(error);
      if (isDirty(this.state.document)) {
        if (failure.code === "note_not_found") this.orphan();
        else {
          this.updateDocument({ loadError: failure });
          this.set({ listError: failure });
        }
      } else this.updateDocument({ status: "unreadable", loadError: failure });
    }
  }

  /** Verify an uncertain mutation with fresh state. Never repeats it. */
  async verifyOutcome(): Promise<void> {
    const unknown = this.state.unknown;
    const vault = this.state.vault;
    if (unknown === null || unknown.verifying) return;
    if (!backendReady(this.state) || vault === null || vault.id !== unknown.attempt.vaultId) {
      this.set({
        unknown: {
          ...unknown,
          verifyError: localError("backend_unavailable", "Page Core and the vault must be open before verifying."),
        },
      });
      return;
    }
    const ticket = this.ticket();
    this.set({ unknown: { ...unknown, verifying: true, verifyError: null } });
    try {
      const counts = await this.api.vaultReconcile(vault.id, {});
      if (!this.owns(ticket, "vault")) return;
      const notes = await this.api.noteList(vault.id);
      if (!this.owns(ticket, "vault")) return;
      this.set({ notes, lastReconcile: counts, listError: null });
      const message = await this.observe(unknown.attempt, notes);
      if (this.owns(ticket, "vault")) {
        this.set({ unknown: null });
        this.announce(message);
      }
    } catch (error) {
      if (!this.owns(ticket, "vault")) return;
      this.set({ unknown: { ...unknown, verifying: false, verifyError: toDesktopError(error) } });
    }
  }

  /** Compare fresh state with an attempted mutation and update the workspace to match it. */
  private async observe(attempt: Attempt, notes: NoteSummaryResponse[]): Promise<string> {
    const vault = this.state.vault;
    if (vault === null) return "";
    const ticket = this.ticket();
    const byId = attempt.noteId === null ? undefined : notes.find((note) => note.id === attempt.noteId);
    switch (attempt.operation) {
      case "create": {
        const created = notes.find((note) => note.relative_path === attempt.path);
        if (created === undefined) return `${attempt.path} was not created. You can try again.`;
        const note = await this.api.noteRead(vault.id, created.id);
        if (!this.owns(ticket, "document")) return "";
        const document = this.state.document;
        if (document?.status === "orphaned" && note.content !== document.draft) {
          return `A note exists at ${attempt.path}, but its content differs from your draft, which is still kept.`;
        }
        this.documentEpoch += 1;
        this.set({ document: this.documentFrom(note), conflict: null });
        this.remember(vault, note.id);
        return `${attempt.path} was created.`;
      }
      case "delete": {
        if (byId === undefined) {
          if (this.state.document?.noteId === attempt.noteId) {
            this.documentEpoch += 1;
            this.set({ document: null });
          }
          return `${attempt.path} was deleted.`;
        }
        await this.refreshDocument(notes);
        return `${attempt.path} was not deleted.`;
      }
      case "move": {
        if (byId === undefined) {
          await this.refreshDocument(notes);
          return `The note is no longer in the vault.`;
        }
        const note = await this.api.noteRead(vault.id, byId.id);
        if (!this.owns(ticket, "document")) return "";
        if (this.state.document?.noteId === note.id && !isDirty(this.state.document)) {
          this.set({ document: this.documentFrom(note) });
        } else {
          await this.refreshDocument(notes);
        }
        return note.relative_path === attempt.path
          ? `The note was moved to ${attempt.path}.`
          : `The note was not moved; it is at ${note.relative_path}.`;
      }
      case "update": {
        if (byId === undefined) {
          if (this.state.document?.noteId === attempt.noteId) this.orphan();
          return `The note no longer exists.`;
        }
        const note = await this.api.noteRead(vault.id, byId.id);
        if (!this.owns(ticket, "document")) return "";
        if (note.content === attempt.content) {
          this.acknowledge(note);
          return `The save of ${note.relative_path} was applied.`;
        }
        if (note.revision === attempt.baseRevision) {
          return `The save of ${note.relative_path} was not applied; your draft is still unsaved.`;
        }
        await this.openConflict(note.id, null);
        return `${note.relative_path} changed differently on disk; compare it with your draft.`;
      }
    }
  }

  // --- Quit ----------------------------------------------------------------

  /** Native close, Cmd+Q and menu Quit all arrive here; repeated requests do not stack. */
  async requestQuit(): Promise<void> {
    if (this.client === null || this.state.quitting || this.state.guard !== null || this.quitRequested) return;
    this.quitRequested = true;
    try {
      await Promise.allSettled([...this.mutationJobs]);
      await this.guarded("quit Page", async () => {
        if (this.state.quitting) return;
        this.set({ quitting: true });
        await this.preferenceWrites;
        try {
          await this.api.desktopQuit();
        } catch (error) {
          this.set({ quitting: false, backendError: toDesktopError(error) });
        }
      });
    } finally {
      this.quitRequested = false;
    }
  }
}
