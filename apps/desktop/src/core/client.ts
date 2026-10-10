import type {
  GraphResponse,
  BackendStatus,
  DesktopPreferences,
  NoteResponse,
  NoteSummaryResponse,
  ReconcileResponse,
  VaultResponse,
} from "./types";
import { toDesktopError } from "./types";

/** Typed access to the Rust commands. Rejections are always DesktopError values. */
export interface PageClient {
  backendStart(): Promise<BackendStatus>;
  backendStatus(): Promise<BackendStatus>;
  backendRestart(): Promise<BackendStatus>;
  vaultCreate(rootPath: string, name: string): Promise<VaultResponse>;
  vaultOpen(rootPath: string): Promise<VaultResponse>;
  vaultList(): Promise<VaultResponse[]>;
  vaultGet(vaultId: string): Promise<VaultResponse>;
  vaultClose(vaultId: string): Promise<void>;
  vaultReconcile(vaultId: string, knownRenames: Record<string, string>): Promise<ReconcileResponse>;
  graphRead(vaultId: string): Promise<GraphResponse>;
  noteList(vaultId: string): Promise<NoteSummaryResponse[]>;
  noteRead(vaultId: string, noteId: string): Promise<NoteResponse>;
  noteCreate(vaultId: string, relativePath: string, content: string): Promise<NoteResponse>;
  noteUpdate(vaultId: string, noteId: string, revision: string, content: string): Promise<NoteResponse>;
  noteMove(vaultId: string, noteId: string, revision: string, relativePath: string): Promise<NoteResponse>;
  noteDelete(vaultId: string, noteId: string, revision: string): Promise<void>;
  preferencesRead(): Promise<DesktopPreferences>;
  preferencesWrite(preferences: DesktopPreferences): Promise<void>;
  desktopQuit(): Promise<void>;
  /** Resolves to an unsubscribe function. */
  onBackendStatus(handler: (status: BackendStatus) => void): Promise<() => void>;
  onQuitRequested(handler: () => void): Promise<() => void>;
}

export type InvokeFn = (command: string, args?: Record<string, unknown>) => Promise<unknown>;
export type ListenFn = (event: string, handler: (payload: unknown) => void) => Promise<() => void>;

export const BACKEND_STATUS_EVENT = "backend-status";
export const QUIT_REQUESTED_EVENT = "quit-requested";

/**
 * Commands use `rename_all = "snake_case"` in Rust, so every argument name
 * below is the exact snake_case key the handler expects.
 */
export function createPageClient(invoke: InvokeFn, listen: ListenFn): PageClient {
  async function call<T>(command: string, args?: Record<string, unknown>): Promise<T> {
    try {
      return (await (args === undefined ? invoke(command) : invoke(command, args))) as T;
    } catch (error) {
      throw toDesktopError(error);
    }
  }

  return {
    backendStart: () => call("backend_start"),
    backendStatus: () => call("backend_status"),
    backendRestart: () => call("backend_restart"),
    vaultCreate: (rootPath, name) => call("vault_create", { root_path: rootPath, name }),
    vaultOpen: (rootPath) => call("vault_open", { root_path: rootPath }),
    vaultList: () => call("vault_list"),
    vaultGet: (vaultId) => call("vault_get", { vault_id: vaultId }),
    vaultClose: (vaultId) => call("vault_close", { vault_id: vaultId }),
    vaultReconcile: (vaultId, knownRenames) =>
      call("vault_reconcile", { vault_id: vaultId, known_renames: knownRenames }),
    graphRead: (vaultId) => call("graph_read", { vault_id: vaultId }),
    noteList: (vaultId) => call("note_list", { vault_id: vaultId }),
    noteRead: (vaultId, noteId) => call("note_read", { vault_id: vaultId, note_id: noteId }),
    noteCreate: (vaultId, relativePath, content) =>
      call("note_create", { vault_id: vaultId, relative_path: relativePath, content }),
    noteUpdate: (vaultId, noteId, revision, content) =>
      call("note_update", { vault_id: vaultId, note_id: noteId, revision, content }),
    noteMove: (vaultId, noteId, revision, relativePath) =>
      call("note_move", { vault_id: vaultId, note_id: noteId, revision, relative_path: relativePath }),
    noteDelete: (vaultId, noteId, revision) =>
      call("note_delete", { vault_id: vaultId, note_id: noteId, revision }),
    preferencesRead: () => call("preferences_read"),
    preferencesWrite: (preferences) => call("preferences_write", { preferences }),
    desktopQuit: () => call("desktop_quit"),
    onBackendStatus: (handler) =>
      listen(BACKEND_STATUS_EVENT, (payload) => handler(payload as BackendStatus)),
    onQuitRequested: (handler) => listen(QUIT_REQUESTED_EVENT, () => handler()),
  };
}

/** True only inside the Tauri webview; an ordinary browser has no IPC bridge. */
export function desktopRuntimeAvailable(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/** The production client, loaded lazily so browser builds never touch IPC. */
export async function createTauriClient(): Promise<PageClient> {
  const [{ invoke }, { listen }] = await Promise.all([
    import("@tauri-apps/api/core"),
    import("@tauri-apps/api/event"),
  ]);
  return createPageClient(
    (command, args) => invoke(command, args),
    (event, handler) => listen(event, (message) => handler(message.payload)),
  );
}
