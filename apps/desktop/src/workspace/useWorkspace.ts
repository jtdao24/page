import { useSyncExternalStore } from "react";
import type { WorkspaceController, WorkspaceState } from "./controller";

export function useWorkspace(controller: WorkspaceController): WorkspaceState {
  return useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);
}
