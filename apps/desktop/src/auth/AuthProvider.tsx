import { createContext, useContext, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { unconfiguredAuthService } from "./service";
import type { AuthService } from "./service";

const AuthContext = createContext<AuthService>(unconfiguredAuthService);

export function AuthProvider({ service = unconfiguredAuthService, children }: { service?: AuthService; children: ReactNode }) {
  return <AuthContext.Provider value={service}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const service = useContext(AuthContext);
  const state = useSyncExternalStore(
    (listener) => service.subscribe(listener),
    () => service.getSnapshot(),
    () => service.getSnapshot(),
  );
  return { service, state };
}
