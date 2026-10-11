import { useEffect, useState } from "react";
import { createTauriClient, desktopRuntimeAvailable } from "./core/client";
import { WorkspaceController } from "./workspace/controller";
import { Workspace } from "./components/Workspace";
import { INTRO_SEEN_KEY, Intro } from "./components/Intro";

function introSeen(): boolean {
  try {
    return localStorage.getItem(INTRO_SEEN_KEY) === "1";
  } catch {
    return true;
  }
}

function App() {
  const [controller, setController] = useState<WorkspaceController | null>(() =>
    desktopRuntimeAvailable() ? null : new WorkspaceController(null),
  );
  const [intro, setIntro] = useState(() => !introSeen());
  const finishIntro = () => {
    try { localStorage.setItem(INTRO_SEEN_KEY, "1"); } catch { /* storage unavailable: show again next time */ }
    setIntro(false);
  };
  useEffect(() => {
    if (!desktopRuntimeAvailable()) return;
    let active = true;
    void createTauriClient().then((client) => {
      if (active) setController(new WorkspaceController(client));
    });
    return () => { active = false; };
  }, []);
  return <>
    {controller === null
      ? <main className="app-starting" role="status"><span className="dots" aria-hidden="true"><i /><i /><i /></span>Starting Page…</main>
      : <Workspace controller={controller} onShowIntro={() => setIntro(true)} />}
    {intro && <Intro onDone={finishIntro} />}
  </>;
}

export default App;
