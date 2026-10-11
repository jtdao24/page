import { describe, expect, it, vi } from "vitest";
import { createPageClient } from "./client";
import { emptyPreferences } from "./types";

describe("typed IPC mapping", () => {
  it("maps every fixed command and snake_case argument explicitly", async () => {
    const invoke = vi.fn<(command: string, args?: Record<string, unknown>) => Promise<unknown>>(async () => undefined);
    const client = createPageClient(invoke, async () => () => {});
    await client.backendStart(); await client.backendStatus(); await client.backendRestart();
    await client.vaultCreate("/tmp/vault", "Notes"); await client.vaultOpen("/tmp/vault");
    await client.vaultList(); await client.vaultGet("vault"); await client.vaultClose("vault");
    await client.vaultReconcile("vault", { note: "new.md" }); await client.noteList("vault"); await client.graphRead("vault");
    await client.semanticIndex("vault", true); await client.semanticSearch("vault", "query", 5);
    await client.askQuestion("vault", "why?", 1500);
    await client.sourceList("vault"); await client.sourceRead("vault", "src"); await client.webPageSave("vault", "https://a.b");
    await client.noteRead("vault", "note"); await client.noteCreate("vault", "new.md", "text");
    await client.noteUpdate("vault", "note", "revision", "text");
    await client.noteMove("vault", "note", "revision", "new.md");
    await client.noteDelete("vault", "note", "revision");
    await client.preferencesRead(); await client.preferencesWrite(emptyPreferences()); await client.desktopQuit();
    await client.geminiKeyStatus(); await client.geminiKeySave("key"); await client.geminiKeyClear();
    await client.pickFolder("Choose");
    expect(invoke.mock.calls).toEqual([
      ["backend_start"], ["backend_status"], ["backend_restart"],
      ["vault_create", { root_path: "/tmp/vault", name: "Notes" }], ["vault_open", { root_path: "/tmp/vault" }],
      ["vault_list"], ["vault_get", { vault_id: "vault" }], ["vault_close", { vault_id: "vault" }],
      ["vault_reconcile", { vault_id: "vault", known_renames: { note: "new.md" } }],
      ["note_list", { vault_id: "vault" }], ["graph_read", { vault_id: "vault" }],
      ["semantic_index", { vault_id: "vault", rebuild: true }], ["semantic_search", { vault_id: "vault", query: "query", limit: 5 }],
      ["ask_question", { vault_id: "vault", question: "why?", budget: 1500 }],
      ["source_list", { vault_id: "vault" }], ["source_read", { vault_id: "vault", source_id: "src" }],
      ["web_page_save", { vault_id: "vault", url: "https://a.b" }], ["note_read", { vault_id: "vault", note_id: "note" }],
      ["note_create", { vault_id: "vault", relative_path: "new.md", content: "text" }],
      ["note_update", { vault_id: "vault", note_id: "note", revision: "revision", content: "text" }],
      ["note_move", { vault_id: "vault", note_id: "note", revision: "revision", relative_path: "new.md" }],
      ["note_delete", { vault_id: "vault", note_id: "note", revision: "revision" }],
      ["preferences_read"], ["preferences_write", { preferences: emptyPreferences() }], ["desktop_quit"],
      ["gemini_key_status"], ["gemini_key_save", { key: "key" }], ["gemini_key_clear"],
      ["plugin:dialog|open", { options: { directory: true, multiple: false, title: "Choose" } }],
    ]);
  });
  it("does not display arbitrary rejected data", async () => {
    const client = createPageClient(async () => { throw "secret credential"; }, async () => () => {});
    await expect(client.backendStart()).rejects.toMatchObject({ code: "unexpected_failure", kind: "protocol" });
  });
});
