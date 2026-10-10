import { vi } from "vitest";
import type { PageClient } from "../core/client";
import { emptyPreferences, type BackendStatus, type DesktopError, type NoteResponse, type VaultResponse } from "../core/types";

export const vault: VaultResponse = { id: "11111111-1111-4111-8111-111111111111", name: "Test Vault", root_path: "/tmp/page-test", needs_reconciliation: false };
export const ready: BackendStatus = { state: "ready", generation: 1, core_version: "0.1.0", error: null };
export const counts = { added: 0, modified: 0, renamed: 0, missing: 0, unchanged: 1 };
export function note(id = "22222222-2222-4222-8222-222222222222", content = "original", path = "a.md"): NoteResponse {
  return { id, vault_id: vault.id, relative_path: path, created_at: "2026-01-01T00:00:00+00:00", updated_at: "2026-01-01T00:00:00+00:00", revision: "a".repeat(64), content };
}
export function failure(code: string, details: DesktopError["details"] = null): DesktopError {
  return { kind: "api", status: 409, code, message: "Operation failed.", details };
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
/** Mock only the external IPC boundary; controller and editor stay real. */
export function testClient() {
  let statusHandler: ((status: BackendStatus) => void) | undefined;
  const client = {
    backendStart: vi.fn(async () => ready), backendStatus: vi.fn(async () => ready),
    backendRestart: vi.fn(async () => ({ ...ready, generation: 2 })),
    vaultCreate: vi.fn(async () => vault), vaultOpen: vi.fn(async () => vault),
    vaultList: vi.fn(async () => [vault]), vaultGet: vi.fn(async () => vault),
    vaultClose: vi.fn(async () => {}), vaultReconcile: vi.fn(async () => counts),
    graphRead: vi.fn<PageClient["graphRead"]>(async () => ({ vault_id: vault.id, nodes: [], links: [] })),
    noteList: vi.fn(async () => [note()]),
    noteRead: vi.fn(async (_vaultId: string, id: string) => note(id)),
    noteCreate: vi.fn(async (_vaultId: string, path: string, content: string) => note(undefined, content, path)),
    noteUpdate: vi.fn(async (_vaultId: string, id: string, _revision: string, content: string) => ({ ...note(id, content), revision: "b".repeat(64) })),
    noteMove: vi.fn(async (_vaultId: string, id: string, _revision: string, path: string) => note(id, "original", path)),
    noteDelete: vi.fn(async () => {}), preferencesRead: vi.fn(async () => emptyPreferences()),
    preferencesWrite: vi.fn(async () => {}), desktopQuit: vi.fn(async () => {}),
    onBackendStatus: vi.fn(async (handler: (status: BackendStatus) => void) => {
      statusHandler = handler;
      return () => { if (statusHandler === handler) statusHandler = undefined; };
    }),
    onQuitRequested: vi.fn(async () => () => {}),
  } satisfies PageClient;
  return { client, emit: (status: BackendStatus) => statusHandler?.(status) };
}
