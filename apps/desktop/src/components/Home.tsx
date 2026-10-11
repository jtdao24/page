import { useState } from "react";
import pageIcon from "../assets/page-icon.png";
import { navigationBlocked, type WorkspaceController, type WorkspaceState } from "../workspace/controller";
import { ErrorText } from "./ErrorText";
import { Icon, type IconName } from "./Icon";
import { VaultForms } from "./VaultForms";

type Choice = "sample" | "create" | "open";

const CHOICES: { id: Choice; icon: IconName; title: string; text: string; pick: string }[] = [
  { id: "sample", icon: "sparkle", title: "Start with a sample", text: "A few short notes that show you around. Best for your first time.",
    pick: "Choose where to put the sample vault" },
  { id: "create", icon: "plus", title: "Create a new vault", text: "Pick an empty folder, or one that already has Markdown notes.",
    pick: "Choose a folder for your new vault" },
  { id: "open", icon: "folder", title: "Open a vault", text: "Continue in a folder you've used with Page before.",
    pick: "Choose a vault folder" },
];

/** The first screen: friendly choices with a folder picker, recent vaults, and a link to the intro. */
export function Home({ controller, state, onShowIntro }: {
  controller: WorkspaceController; state: WorkspaceState; onShowIntro?: () => void;
}) {
  const [busy, setBusy] = useState<Choice | null>(null);
  const [typed, setTyped] = useState(false);
  const disabled = navigationBlocked(state) || busy !== null;
  const recents = state.preferences.recent_vaults.slice(0, 4);

  async function choose(choice: (typeof CHOICES)[number]) {
    setBusy(choice.id);
    try {
      const folder = await controller.pickFolder(choice.pick);
      if (folder === null) return;
      if (choice.id === "sample") await controller.createSampleVault(folder);
      else if (choice.id === "create") await controller.createVault(folder, folder.split(/[\\/]/).filter(Boolean).at(-1) ?? "Notes");
      else await controller.openVault(folder);
    } finally {
      setBusy(null);
    }
  }

  return <div className="home">
    <header className="home-hero">
      <img className="home-icon" src={pageIcon} alt="" width={88} height={88} />
      <h2>Welcome to Page</h2>
      <p>A calm home for your notes, PDFs and saved web pages. Find things by meaning, see how ideas connect,
        and ask questions about what you've written. Everything stays in a folder on your Mac.</p>
      {onShowIntro && <button className="link-button" onClick={onShowIntro}>Take the 30-second tour</button>}
    </header>
    <div className="home-choices">
      {CHOICES.map((choice, index) => <button key={choice.id} className={`home-card ${choice.id === "sample" ? "is-recommended" : ""}`}
        style={{ animationDelay: `${80 + index * 70}ms` }} disabled={disabled} onClick={() => void choose(choice)}>
        <span className="home-card-icon"><Icon name={choice.icon} size={20} /></span>
        <span className="home-card-title">{choice.title}{choice.id === "sample" && <em>Recommended</em>}</span>
        <span className="home-card-text">{busy === choice.id ? "Waiting for you to choose a folder…" : choice.text}</span>
      </button>)}
    </div>
    {state.vaultError !== null && !typed && <p role="alert" className="home-error"><ErrorText error={state.vaultError} /></p>}
    {recents.length > 0 && <section className="home-recents" aria-label="Recent vaults">
      <h3>Recent</h3>
      {recents.map((entry) => <button key={entry.vault_id} className="home-recent" disabled={disabled}
        onClick={() => void controller.openRecent(entry)}>
        <Icon name="vault" size={15} /><span>{entry.root_path.split(/[\\/]/).filter(Boolean).at(-1)}</span>
        <small>{entry.root_path}</small>
      </button>)}
    </section>}
    <details className="home-typed" open={typed} onToggle={(event) => setTyped(event.currentTarget.open)}>
      <summary>Type a folder path instead</summary>
      <VaultForms controller={controller} state={state} />
    </details>
  </div>;
}
