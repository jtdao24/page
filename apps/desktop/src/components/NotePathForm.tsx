import { type FormEvent, useState } from "react";

export function validNotePath(path: string): boolean {
  return path.endsWith(".md") && !path.includes("\\") && !path.includes("\0") &&
    !/^[A-Za-z]:/.test(path) && path.split("/").every((part) => part !== "" && part !== "." && part !== "..") &&
    path.split("/")[0] !== ".page";
}

export function NotePathForm({ initialPath = "", label, disabled, onSubmit, onCancel }: {
  initialPath?: string;
  label: string;
  disabled: boolean;
  onSubmit: (path: string) => Promise<boolean>;
  onCancel: () => void;
}) {
  const [path, setPath] = useState(initialPath);
  const [problem, setProblem] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (disabled) return;
    if (!validNotePath(path)) { setProblem(true); return; }
    setProblem(false);
    await onSubmit(path);
  }
  return <form onSubmit={submit} className="space-y-3">
    <label className="block text-sm">Relative note path
      <input data-autofocus className="mt-1 w-full rounded border p-2" value={path}
        onChange={(event) => setPath(event.target.value)} placeholder="folder/note.md" spellCheck={false} />
    </label>
    {problem && <p role="alert">Use a relative path with / between folders and a lowercase .md ending.</p>}
    <div className="flex gap-2">
      <button type="submit" disabled={disabled}>{label}</button>
      <button type="button" disabled={disabled} onClick={onCancel}>Cancel</button>
    </div>
  </form>;
}
