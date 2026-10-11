import pageIcon from "../assets/page-icon.png";
import { navigationBlocked, type WorkspaceController, type WorkspaceState } from "../workspace/controller";
import { ErrorText } from "./ErrorText";
import { Icon } from "./Icon";
import { folderName, VaultChoices } from "./VaultChoices";

/** The first screen: friendly choices that open Finder, recent vaults, and a link to the intro. */
export function Home({ controller, state, onShowIntro }: {
  controller: WorkspaceController; state: WorkspaceState; onShowIntro?: () => void;
}) {
  const recents = state.preferences.recent_vaults.slice(0, 4);
  return <div className="home">
    <header className="home-hero">
      <img className="home-icon" src={pageIcon} alt="" width={88} height={88} />
      <h2>Welcome to Page</h2>
      <p>A calm home for your notes, PDFs and saved web pages. Find things by meaning, see how ideas connect,
        and ask questions about what you've written. Everything stays in a folder on your Mac.</p>
      {onShowIntro && <button className="link-button" onClick={onShowIntro}>Take the 30-second tour</button>}
    </header>
    <VaultChoices controller={controller} state={state} />
    {state.vaultError !== null && <p role="alert" className="home-error"><ErrorText error={state.vaultError} /></p>}
    {recents.length > 0 && <section className="home-recents" aria-label="Recent vaults">
      <h3>Recent</h3>
      {recents.map((entry) => <button key={entry.vault_id} className="home-recent" disabled={navigationBlocked(state)}
        onClick={() => void controller.openRecent(entry)}>
        <Icon name="vault" size={15} /><span>{folderName(entry.root_path)}</span><small>{entry.root_path}</small>
      </button>)}
    </section>}
  </div>;
}
