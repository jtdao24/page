import { useState } from "react";
import { navigationBlocked, type WorkspaceController, type WorkspaceState } from "../workspace/controller";
import { Icon, type IconName } from "./Icon";

type Choice = "sample" | "create" | "open";

const CHOICES: { id: Choice; icon: IconName; title: string; text: string; pick: string }[] = [
  { id: "sample", icon: "sparkle", title: "Start with a sample", text: "A few short notes that show you around. Best for your first time.",
    pick: "Choose where to put the sample vault" },
  { id: "create", icon: "plus", title: "Create a new vault", text: "Pick an empty folder, or one that already has Markdown notes.",
    pick: "Choose a folder for your new vault" },
  { id: "open", icon: "folder", title: "Open a vault", text: "Continue in a folder you've used with Page before.",
    pick: "Choose a vault folder" },
];

export function folderName(path: string): string {
  return path.split(/[\\/]/).filter(Boolean).at(-1) ?? "Notes";
}

/** Open the Finder folder picker and open the chosen vault. Resolves false if cancelled or it failed. */
export async function openVaultWithPicker(controller: WorkspaceController): Promise<boolean> {
  const folder = await controller.pickFolder("Choose a vault folder");
  return folder !== null && (await controller.openVault(folder)) === true;
}

/** The three ways to start, each choosing its folder in Finder; nothing is typed. */
export function VaultChoices({ controller, state, onDone }: {
  controller: WorkspaceController; state: WorkspaceState; onDone?: () => void;
}) {
  const [busy, setBusy] = useState<Choice | null>(null);
  const disabled = navigationBlocked(state) || busy !== null;

  async function choose(choice: (typeof CHOICES)[number]) {
    setBusy(choice.id);
    try {
      const folder = await controller.pickFolder(choice.pick);
      if (folder === null) return;
      const done = choice.id === "sample" ? await controller.createSampleVault(folder)
        : choice.id === "create" ? await controller.createVault(folder, folderName(folder))
        : await controller.openVault(folder);
      if (done) onDone?.();
    } finally {
      setBusy(null);
    }
  }

  return <div className="home-choices">
    {CHOICES.map((choice, index) => <button key={choice.id} className={`home-card ${choice.id === "sample" ? "is-recommended" : ""}`}
      style={{ animationDelay: `${80 + index * 70}ms` }} disabled={disabled} onClick={() => void choose(choice)}>
      <span className="home-card-icon"><Icon name={choice.icon} size={20} /></span>
      <span className="home-card-title">{choice.title}{choice.id === "sample" && <em>Recommended</em>}</span>
      <span className="home-card-text">{busy === choice.id ? "Choose a folder in the window that opened…" : choice.text}</span>
    </button>)}
  </div>;
}
