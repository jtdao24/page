import { describe, expect, it } from "vitest";
import { WorkspaceController, isDirty, mutationsBlocked } from "./controller";
import { deferred, failure, note, ready, testClient, vault } from "./testClient";
import type { NoteResponse } from "../core/types";

async function setup() {
  const mock = testClient();
  const controller = new WorkspaceController(mock.client);
  await controller.start();
  await controller.openVault(vault.root_path);
  await controller.selectNote(note().id);
  function draft(text = "draft") {
    const document = controller.getState().document!;
    controller.setDraft(document.noteId, document.editorKey, text);
  }
  return { ...mock, controller, draft };
}

describe("workspace actions", () => {
  it("starts and restores once, without saving", async () => {
    const { client } = testClient();
    client.preferencesRead.mockResolvedValue({ version: 1, active_vault_id: vault.id, recent_vaults: [{ vault_id: vault.id, root_path: vault.root_path, last_note_id: note().id }] });
    const controller = new WorkspaceController(client);
    await Promise.all([controller.start(), controller.start()]);
    expect(client.backendStart).toHaveBeenCalledTimes(1);
    expect(client.vaultOpen).toHaveBeenCalledTimes(1);
    expect(controller.getState().document?.draft).toBe("original");
    expect(client.noteUpdate).not.toHaveBeenCalled();
  });
  it("does not save a clean document", async () => {
    const { client, controller } = await setup();
    expect(await controller.save()).toBe(true);
    expect(client.noteUpdate).not.toHaveBeenCalled();
  });
  it("keeps later typing dirty and prevents duplicate writes", async () => {
    const { client, controller, draft } = await setup();
    const pending = deferred<NoteResponse>();
    client.noteUpdate.mockReturnValueOnce(pending.promise);
    draft("submitted");
    const save = controller.save();
    await controller.save();
    draft("newer typing");
    pending.resolve({ ...note(undefined, "submitted"), revision: "b".repeat(64) });
    expect(await save).toBe(false);
    expect(client.noteUpdate).toHaveBeenCalledTimes(1);
    expect(controller.getState().document?.accepted?.content).toBe("submitted");
    expect(controller.getState().document?.draft).toBe("newer typing");
    expect(isDirty(controller.getState().document)).toBe(true);
  });
  it("cancel and discard never write; failed save blocks navigation", async () => {
    const { client, controller, draft } = await setup();
    draft();
    const canceled = controller.closeVault();
    controller.guardCancel();
    await canceled;
    expect(client.vaultClose).not.toHaveBeenCalled();
    const failed = controller.closeVault();
    client.noteUpdate.mockRejectedValueOnce(failure("filesystem_forbidden"));
    await controller.guardSave();
    await failed;
    expect(client.vaultClose).not.toHaveBeenCalled();
    expect(controller.getState().document?.draft).toBe("draft");
    const discarded = controller.closeVault();
    await controller.guardDiscard();
    expect(await discarded).toBe(true);
    expect(client.noteUpdate).toHaveBeenCalledTimes(1);
  });
  it("new typing during guard save blocks the transition", async () => {
    const { client, controller, draft } = await setup();
    draft();
    const pending = deferred<NoteResponse>();
    client.noteUpdate.mockReturnValueOnce(pending.promise);
    const transition = controller.closeVault();
    const save = controller.guardSave();
    draft("later");
    controller.guardCancel();
    pending.resolve(note(undefined, "draft"));
    await save;
    await transition;
    expect(client.vaultClose).not.toHaveBeenCalled();
    expect(controller.getState().document?.draft).toBe("later");
  });
  it("slow A read cannot replace B", async () => {
    const { client, controller } = await setup();
    const pending = deferred<NoteResponse>();
    const a = "33333333-3333-4333-8333-333333333333";
    const b = "44444444-4444-4444-8444-444444444444";
    client.noteRead.mockReturnValueOnce(pending.promise);
    const selecting = controller.selectNote(a);
    expect(controller.getState().document?.draft).toBe("");
    await controller.selectNote(b);
    pending.resolve(note(a, "stale"));
    await selecting;
    expect(controller.getState().document?.noteId).toBe(b);
    expect(controller.getState().document?.draft).toBe("original");
  });
  it("old vault list errors cannot alter a newer vault", async () => {
    const { client, controller } = await setup();
    const pending = deferred<NoteResponse[]>();
    client.noteList.mockReturnValueOnce(pending.promise);
    const listing = controller.reloadNotes();
    client.vaultOpen.mockResolvedValueOnce({ ...vault, id: "55555555-5555-4555-8555-555555555555", name: "Other" });
    await controller.openVault("/tmp/other");
    pending.reject(failure("old_error"));
    await listing;
    expect(controller.getState().vault?.name).toBe("Other");
    expect(controller.getState().listError).toBeNull();
  });
  it("acknowledged save remains saved when collection refresh fails", async () => {
    const { client, controller, draft } = await setup();
    draft();
    client.noteList.mockRejectedValueOnce(failure("storage_busy"));
    expect(await controller.save()).toBe(true);
    await Promise.resolve();
    expect(isDirty(controller.getState().document)).toBe(false);
    expect(controller.getState().listError?.code).toBe("storage_busy");
    expect(controller.getState().actionError).toBeNull();
  });
  it("conflicts keep drafts and use only the freshly read revision", async () => {
    const { client, controller, draft } = await setup();
    draft();
    client.noteUpdate.mockRejectedValueOnce(failure("revision_conflict"));
    client.noteRead.mockResolvedValueOnce({ ...note(undefined, "disk"), revision: "c".repeat(64) });
    await controller.save();
    await Promise.resolve();
    expect(controller.getState().document?.draft).toBe("draft");
    expect(controller.getState().conflict?.server?.content).toBe("disk");
    await controller.conflictUseDraft();
    expect(client.noteUpdate).toHaveBeenLastCalledWith(vault.id, note().id, "c".repeat(64), "draft");
  });
  it("unknown save is verified without repeating the mutation", async () => {
    const { client, controller, draft } = await setup();
    draft();
    client.noteUpdate.mockRejectedValueOnce(failure("mutation_outcome_unknown"));
    await controller.save();
    expect(mutationsBlocked(controller.getState())).toBe(true);
    client.noteRead.mockResolvedValueOnce({ ...note(undefined, "draft"), revision: "b".repeat(64) });
    await controller.verifyOutcome();
    expect(controller.getState().unknown).toBeNull();
    expect(isDirty(controller.getState().document)).toBe(false);
    expect(client.noteUpdate).toHaveBeenCalledTimes(1);
  });
  it("verification read failure keeps mutations blocked", async () => {
    const { client, controller, draft } = await setup();
    draft();
    client.noteUpdate.mockRejectedValueOnce(failure("mutation_outcome_unknown"));
    await controller.save();
    client.noteRead.mockRejectedValueOnce(failure("unreadable_note"));
    await controller.verifyOutcome();
    expect(controller.getState().unknown?.verifyError?.code).toBe("unreadable_note");
    expect(mutationsBlocked(controller.getState())).toBe(true);
  });
  it("crash invalidates an in-flight mutation; old result cannot save newer state", async () => {
    const { client, controller, draft, emit } = await setup();
    const detach = controller.attach();
    await Promise.resolve();
    draft();
    const pending = deferred<NoteResponse>();
    client.noteUpdate.mockReturnValueOnce(pending.promise);
    const save = controller.save();
    emit({ ...ready, state: "failed", generation: 2, error: failure("backend_exited") });
    pending.resolve(note(undefined, "draft"));
    await save;
    expect(controller.getState().unknown).not.toBeNull();
    expect(isDirty(controller.getState().document)).toBe(true);
    detach();
  });
  it("restart preserves dirty text and rejects old notifications", async () => {
    const { controller, draft, emit } = await setup();
    const detach = controller.attach();
    await Promise.resolve();
    draft();
    await controller.restart();
    emit({ ...ready, state: "failed", error: failure("old_failure") });
    expect(controller.getState().backend?.generation).toBe(2);
    expect(controller.getState().backend?.state).toBe("ready");
    expect(controller.getState().document?.draft).toBe("draft");
    detach();
  });
  it("restart during save preserves uncertainty and never replays the write", async () => {
    const { client, controller, draft } = await setup();
    const pending = deferred<NoteResponse>(); client.noteUpdate.mockReturnValueOnce(pending.promise);
    draft(); const saving = controller.save();
    await controller.restart();
    pending.resolve(note(undefined, "draft")); await saving;
    expect(controller.getState().unknown?.attempt.operation).toBe("update");
    expect(controller.getState().document?.draft).toBe("draft");
    expect(isDirty(controller.getState().document)).toBe(true);
    expect(client.noteUpdate).toHaveBeenCalledTimes(1);
  });
  it("move conflicts offer a fresh disk snapshot without moving again", async () => {
    const { client, controller } = await setup();
    client.noteMove.mockRejectedValueOnce(failure("revision_conflict"));
    client.noteRead.mockResolvedValueOnce({ ...note(undefined, "disk edit"), revision: "c".repeat(64) });
    expect(await controller.moveNote("new.md")).toBe(false);
    await Promise.resolve();
    expect(controller.getState().conflict?.server?.content).toBe("disk edit");
    expect(controller.getState().document?.path).toBe("a.md");
    expect(client.noteMove).toHaveBeenCalledTimes(1);
  });
  it("metadata failure requires recovery and sends only the confirmed move", async () => {
    const { client, controller } = await setup();
    client.noteMove.mockRejectedValueOnce(failure("metadata_sync_failed", { operation: "move", relative_path: "nested/new.md", note_id: note().id }));
    await controller.moveNote("nested/new.md");
    expect(mutationsBlocked(controller.getState())).toBe(true);
    client.vaultReconcile.mockRejectedValueOnce(failure("storage_busy"));
    await controller.reconcileRecovery();
    expect(controller.getState().recovery?.working).toBe(false);
    await controller.confirmFailedMove();
    expect(client.vaultReconcile).toHaveBeenLastCalledWith(vault.id, { [note().id]: "nested/new.md" });
    expect(controller.getState().recovery).toBeNull();
  });
  it("missing notes retain orphan drafts for explicit creation", async () => {
    const { client, controller, draft } = await setup();
    draft();
    client.noteUpdate.mockRejectedValueOnce(failure("note_not_found"));
    await controller.save();
    expect(controller.getState().document?.status).toBe("orphaned");
    await controller.saveOrphanAs("rescued.md");
    expect(client.noteCreate).toHaveBeenCalledWith(vault.id, "rescued.md", "draft");
  });
  it("refresh does not replace typing that starts while a clean read is pending", async () => {
    const { client, controller, draft } = await setup();
    client.noteList.mockResolvedValueOnce([{ ...note(), revision: "b".repeat(64) }]);
    const pending = deferred<NoteResponse>();
    client.noteRead.mockReturnValueOnce(pending.promise);
    const refresh = controller.refreshFromDisk();
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    draft("typed during refresh");
    pending.resolve({ ...note(undefined, "disk"), revision: "b".repeat(64) });
    await refresh;
    expect(controller.getState().document?.draft).toBe("typed during refresh");
    expect(controller.getState().conflict).not.toBeNull();
  });
  it("malformed preferences remain preserved until explicit reset", async () => {
    const { client } = testClient();
    client.preferencesRead.mockRejectedValueOnce(failure("preferences_invalid"));
    const controller = new WorkspaceController(client);
    await controller.start(); await controller.openVault(vault.root_path); await controller.flushPreferences();
    expect(client.preferencesWrite).not.toHaveBeenCalled();
    await controller.resetPreferences();
    expect(client.preferencesWrite).toHaveBeenCalledTimes(1);
  });
  it("a failed refresh read keeps typing visible and guarded", async () => {
    const { client, controller, draft } = await setup();
    client.noteList.mockResolvedValueOnce([{ ...note(), revision: "b".repeat(64) }]);
    const pending = deferred<NoteResponse>(); client.noteRead.mockReturnValueOnce(pending.promise);
    const refresh = controller.refreshFromDisk();
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    draft("new typing"); pending.reject(failure("unreadable_note")); await refresh;
    expect(controller.getState().document?.status).toBe("ready");
    expect(controller.getState().document?.draft).toBe("new typing");
    expect(isDirty(controller.getState().document)).toBe(true);
    const closing = controller.closeVault(); controller.guardCancel(); await closing;
    expect(client.vaultClose).not.toHaveBeenCalled();
  });
  it("newest list wins when same-vault refreshes finish out of order", async () => {
    const { client, controller } = await setup();
    const pending = deferred<NoteResponse[]>(); client.noteList.mockReturnValueOnce(pending.promise);
    const oldList = controller.reloadNotes();
    client.noteList.mockResolvedValueOnce([note(undefined, "", "new.md")]); await controller.reloadNotes();
    pending.resolve([note(undefined, "", "old.md")]); await oldList;
    expect(controller.getState().notes?.[0].relative_path).toBe("new.md");
  });
  it("settings failure does not relabel an acknowledged note save", async () => {
    const { client, controller, draft } = await setup();
    await controller.flushPreferences();
    client.preferencesWrite.mockRejectedValueOnce(failure("preferences_write_failed"));
    await controller.selectNote("33333333-3333-4333-8333-333333333333");
    await controller.flushPreferences(); draft("saved despite settings");
    await controller.save();
    expect(isDirty(controller.getState().document)).toBe(false);
    expect(controller.getState().preferencesWriteError?.code).toBe("preferences_write_failed");
    expect(controller.getState().actionError).toBeNull();
  });
  it("missing remembered roots and changed identities never create vaults", async () => {
    const { client } = testClient();
    client.preferencesRead.mockResolvedValue({ version: 1, active_vault_id: vault.id, recent_vaults: [{ vault_id: vault.id, root_path: vault.root_path, last_note_id: null }] });
    client.vaultOpen.mockRejectedValueOnce(failure("vault_not_found"));
    const controller = new WorkspaceController(client);
    await controller.start();
    expect(controller.getState().vaultError?.code).toBe("vault_not_found");
    client.vaultOpen.mockResolvedValueOnce({ ...vault, id: "55555555-5555-4555-8555-555555555555" });
    await controller.openRecent(controller.getState().preferences.recent_vaults[0]);
    expect(controller.getState().identity).not.toBeNull();
    expect(controller.getState().vault).toBeNull();
    expect(client.vaultCreate).not.toHaveBeenCalled();
  });
  it("native quit waits for a pending save and supports cancellation", async () => {
    const { client, controller, draft } = await setup();
    draft();
    const pending = deferred<NoteResponse>();
    client.noteUpdate.mockReturnValueOnce(pending.promise);
    const saving = controller.save();
    const quitting = controller.requestQuit();
    expect(client.desktopQuit).not.toHaveBeenCalled();
    pending.resolve(note(undefined, "draft"));
    await saving; await quitting;
    expect(client.desktopQuit).toHaveBeenCalledTimes(1);
  });
});
