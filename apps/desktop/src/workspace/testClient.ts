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
    semanticIndex: vi.fn<PageClient["semanticIndex"]>(async () => ({ vault_id: vault.id, model: "test", notes: 1, chunks: 1, generated: 1, reused: 0, removed: 0 })),
    semanticSearch: vi.fn<PageClient["semanticSearch"]>(async () => ({ vault_id: vault.id, model: "test", hits: [] })),
    askQuestion: vi.fn<PageClient["askQuestion"]>(async (_vault, _question, budget) => ({
      vault_id: vault.id, model: "test-model", answer: "No notes cover that.", answered_by_model: false,
      finish_reason: "NO_SOURCES", sources: [], cited: [],
      usage: { context_tokens: 0, budget, counter: "utf8-bytes/3", input_tokens: 0, output_tokens: 0, vault_tokens: 0 },
    })),
    sourceList: vi.fn<PageClient["sourceList"]>(async () => []),
    sourceRead: vi.fn<PageClient["sourceRead"]>(async (_vault, id) => ({ id, vault_id: vault.id, relative_path: "papers/a.pdf",
      kind: "pdf", revision: "c".repeat(64), content: "[Page 1]\nsource text" })),
    webPageSave: vi.fn<PageClient["webPageSave"]>(async (_vault, url) => note("44444444-4444-4444-8444-444444444444", `source: ${url}`, "web/example.com/page.md")),
    graphRead: vi.fn<PageClient["graphRead"]>(async () => ({ vault_id: vault.id, nodes: [], links: [] })),
    noteList: vi.fn(async () => [note()]),
    noteRead: vi.fn(async (_vaultId: string, id: string) => note(id)),
    noteCreate: vi.fn(async (_vaultId: string, path: string, content: string) => note(undefined, content, path)),
    noteUpdate: vi.fn(async (_vaultId: string, id: string, _revision: string, content: string) => ({ ...note(id, content), revision: "b".repeat(64) })),
    noteMove: vi.fn(async (_vaultId: string, id: string, _revision: string, path: string) => note(id, "original", path)),
    noteDelete: vi.fn(async () => {}), preferencesRead: vi.fn(async () => emptyPreferences()),
    preferencesWrite: vi.fn(async () => {}), desktopQuit: vi.fn(async () => {}),
    geminiKeyStatus: vi.fn<PageClient["geminiKeyStatus"]>(async () => ({ stored: false, from_environment: false })),
    geminiKeySave: vi.fn<PageClient["geminiKeySave"]>(async () => {}),
    geminiKeyClear: vi.fn<PageClient["geminiKeyClear"]>(async () => {}),
    pickFolder: vi.fn<PageClient["pickFolder"]>(async () => null),
    pickSavePath: vi.fn<PageClient["pickSavePath"]>(async () => null),
    onBackendStatus: vi.fn(async (handler: (status: BackendStatus) => void) => {
      statusHandler = handler;
      return () => { if (statusHandler === handler) statusHandler = undefined; };
    }),
    onQuitRequested: vi.fn(async () => () => {}),
  } satisfies PageClient;
  return { client, emit: (status: BackendStatus) => statusHandler?.(status) };
}
