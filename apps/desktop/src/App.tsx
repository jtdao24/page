import { useEffect, useState } from "react";
import { createTauriClient, desktopRuntimeAvailable } from "./core/client";
import { WorkspaceController } from "./workspace/controller";
import { Workspace } from "./components/Workspace";

function App() {
  const [controller, setController] = useState<WorkspaceController | null>(() =>
    desktopRuntimeAvailable() ? null : new WorkspaceController(null),
  );
  useEffect(() => {
    if (!desktopRuntimeAvailable()) return;
    let active = true;
    void createTauriClient().then((client) => {
      if (active) setController(new WorkspaceController(client));
    });
    return () => { active = false; };
  }, []);
  return controller === null
    ? <main className="p-6" role="status">Starting Page desktop…</main>
    : <Workspace controller={controller} />;
}

export default App;
