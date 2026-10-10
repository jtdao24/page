import { useState } from "react";
import { useAuth } from "./AuthProvider";
import { authErrorMessage, authStatusLabel } from "./service";
import type { AuthRoute } from "./routes";

export function AccountSettings({ onNavigate }: { onNavigate: (route: AuthRoute) => void }) {
  const { service, state } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const user = state.status === "signed-in" ? state.user : null;
  const logout = async () => {
    setPending(true); setError("");
    try { await service.signOut(); }
    catch (cause) { setError(authErrorMessage(cause)); }
    finally { setPending(false); }
  };
  return <section className="account-settings" aria-label="Account settings">
    <div className="account-profile"><span className="account-avatar" aria-hidden="true">{user ? (user.name || user.email).slice(0, 1).toUpperCase() : "○"}</span>
      <div><h3>{user ? user.name || "Your profile" : "Your local workspace"}</h3><p role="status">{authStatusLabel(state)}</p>{user && <p>{user.email}</p>}</div></div>
    <p className="account-intro">Your Markdown vault is available without an online account. Accounts will support preferences, connected services, and synchronization.</p>
    {state.status === "unconfigured" && <p className="account-notice">Sign-in is not yet available. No account provider is configured.</p>}
    {state.status === "error" && <p className="account-notice" role="alert">We couldn’t check your account. Your local vault is still available.</p>}
    <div className="account-actions">{user ? <button className="button button-secondary" disabled={pending} onClick={() => { void logout(); }}>{pending ? "Logging out…" : "Log Out"}</button>
      : <><button className="button button-primary" disabled={state.status === "loading"} onClick={() => onNavigate("/login")}>Log In</button><button className="button button-secondary" disabled={state.status === "loading"} onClick={() => onNavigate("/signup")}>Sign Up</button></>}</div>
    {error && <p role="alert" className="inline-error">{error}</p>}
    <div className="account-section"><h3>Account preferences</h3><p>Profile editing and online preferences will be available when account services are connected.</p><button className="button button-secondary" disabled>Edit profile · coming soon</button></div>
    <div className="account-section"><h3>Connected accounts</h3><p>Connections to Google and GitHub are planned. No connected-account service is configured.</p>
      <div className="account-service-row"><span>Google</span><button disabled>Connect · coming soon</button></div><div className="account-service-row"><span>GitHub</span><button disabled>Connect · coming soon</button></div></div>
    <div className="account-section"><h3>Synchronization</h3><p>Your notes stay on this device. Cross-device sync is not available yet.</p><label className="account-sync"><input type="checkbox" disabled />Enable sync <span>Coming soon</span></label></div>
  </section>;
}
