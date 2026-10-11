import { type FormEvent, useState } from "react";
import { type WorkspaceController, type WorkspaceState, navigationBlocked } from "../workspace/controller";
import { ErrorText } from "./ErrorText";

export function isAbsolutePath(value: string): boolean {
  return value.startsWith("/") || /^[A-Za-z]:[\\/]/.test(value) || value.startsWith("\\\\");
}

interface VaultFormsProps {
  controller: WorkspaceController;
  state: WorkspaceState;
  /** Which form receives focus first. */
  focus?: "create" | "open";
  onDone?: () => void;
}

const inputClass = "w-full rounded border border-neutral-300 px-2 py-1 text-sm focus:outline-2 focus:outline-blue-500";
const buttonClass =
  "rounded bg-blue-600 px-3 py-1 text-sm font-medium text-white disabled:cursor-not-allowed disabled:bg-neutral-300";

/** Separate Create and Open forms; entered values survive failures. */
export function VaultForms({ controller, state, focus = "open", onDone }: VaultFormsProps) {
  const [createRoot, setCreateRoot] = useState("");
  const [name, setName] = useState("");
  const [openRoot, setOpenRoot] = useState("");
  const [problem, setProblem] = useState<{ form: "create" | "open"; text: string } | null>(null);
  const disabled = navigationBlocked(state);
  async function browse(set: (path: string) => void, title: string) {
    const folder = await controller.pickFolder(title);
    if (folder !== null) set(folder);
  }
  const browseButton = (set: (path: string) => void, title: string) =>
    <button type="button" className="browse-button" disabled={disabled} onClick={() => void browse(set, title)}>Browse…</button>;

  async function submitCreate(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    if (!isAbsolutePath(createRoot)) return setProblem({ form: "create", text: "Enter an absolute folder path." });
    if (name.trim() === "") return setProblem({ form: "create", text: "Enter a vault name." });
    setProblem(null);
    if (await controller.createVault(createRoot, name)) onDone?.();
  }

  async function submitOpen(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    if (!isAbsolutePath(openRoot)) return setProblem({ form: "open", text: "Enter an absolute folder path." });
    setProblem(null);
    if (await controller.openVault(openRoot)) onDone?.();
  }

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <form onSubmit={submitOpen} aria-label="Open Vault" className="space-y-2">
        <h3 className="text-sm font-semibold">Open Vault</h3>
        <label className="block text-xs text-neutral-600">
          Vault folder (absolute path)
          <input
            className={inputClass}
            value={openRoot}
            onChange={(event) => setOpenRoot(event.target.value)}
            placeholder="/Users/you/Notes"
            spellCheck={false}
            data-autofocus={focus === "open" ? true : undefined}
            autoFocus={focus === "open"}
          />
        </label>
        {browseButton(setOpenRoot, "Choose a vault folder")}
        {problem?.form === "open" && (
          <p role="alert" className="text-xs text-red-700">
            {problem.text}
          </p>
        )}
        <button type="submit" className={buttonClass} disabled={disabled}>
          Open Vault
        </button>
      </form>
      <form onSubmit={submitCreate} aria-label="Create Vault" className="space-y-2">
        <h3 className="text-sm font-semibold">Create Vault</h3>
        <label className="block text-xs text-neutral-600">
          Folder (absolute path)
          <input
            className={inputClass}
            value={createRoot}
            onChange={(event) => setCreateRoot(event.target.value)}
            placeholder="/Users/you/Notes"
            spellCheck={false}
            data-autofocus={focus === "create" ? true : undefined}
            autoFocus={focus === "create"}
          />
        </label>
        {browseButton((path) => {
          setCreateRoot(path);
          if (!name.trim()) setName(path.split(/[\\/]/).filter(Boolean).at(-1) ?? "");
        }, "Choose a folder for your new vault")}
        <label className="block text-xs text-neutral-600">
          Vault name
          <input className={inputClass} value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <p className="text-xs text-neutral-500">
          The folder is created if needed. Markdown files already in it are adopted as notes without being
          changed. An existing vault is never overwritten.
        </p>
        {problem?.form === "create" && (
          <p role="alert" className="text-xs text-red-700">
            {problem.text}
          </p>
        )}
        <button type="submit" className={buttonClass} disabled={disabled}>
          Create Vault
        </button>
      </form>
      {state.vaultError !== null && (
        <p role="alert" className="text-sm text-red-700 lg:col-span-2">
          <ErrorText error={state.vaultError} />
        </p>
      )}
    </div>
  );
}
