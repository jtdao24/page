import { useEffect, useId, useRef, useState } from "react";
import type { ComponentProps, FormEvent, MouseEvent, ReactNode } from "react";
import { useAuth } from "./AuthProvider";
import { authErrorMessage } from "./service";
import type { FieldErrors } from "./validation";
import type { AuthRoute } from "./routes";

export interface AuthFormProps { onNavigate?: (route: AuthRoute) => void; appHref?: string; onContinue?: () => void }

export function AuthLink({ route, onNavigate, children }: { route: AuthRoute; onNavigate?: AuthFormProps["onNavigate"]; children: ReactNode }) {
  const navigate = (event: MouseEvent<HTMLAnchorElement>) => {
    if (onNavigate && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && event.button === 0) {
      event.preventDefault(); onNavigate(route);
    }
  };
  return <a href={`${route}/`} onClick={navigate}>{children}</a>;
}

export function AuthNotice() {
  const { state } = useAuth();
  if (state.status === "unconfigured") return <div className="auth-notice" role="status"><strong>Sign-in is not yet available.</strong><span>Online accounts aren’t configured. You can use your local workspace without signing in. No credentials are sent.</span></div>;
  if (state.status === "loading") return <p className="auth-notice" role="status">Checking your account…</p>;
  if (state.status === "error") return <p className="auth-notice auth-message--error" role="alert">Your account service is unavailable. Please try again later.</p>;
  return null;
}

export function SocialButtons() {
  return <div className="auth-social"><div className="auth-divider"><span>or, in a future chapter</span></div>
    <button type="button" disabled aria-describedby="social-note"><span className="auth-provider-mark" aria-hidden="true">G</span>Continue with Google</button>
    <button type="button" disabled aria-describedby="social-note"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.86c-2.78.6-3.37-1.18-3.37-1.18-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.89 1.53 2.34 1.09 2.91.83.09-.64.35-1.09.64-1.34-2.22-.25-4.56-1.11-4.56-4.95 0-1.09.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.03A9.6 9.6 0 0 1 12 6.82c.85 0 1.71.11 2.51.34 1.91-1.3 2.75-1.03 2.75-1.03.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.85-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85v2.75c0 .27.18.58.69.48A10 10 0 0 0 12 2Z" /></svg>Continue with GitHub</button>
    <p id="social-note">Google and GitHub sign-in are not connected yet.</p></div>;
}

interface FieldProps extends ComponentProps<"input"> { label: string; error?: string; hint?: string; password?: boolean }
export function AuthField({ label, error, hint, password, ...input }: FieldProps) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  return <div className="auth-field"><label htmlFor={id}>{label}</label><div className="auth-input-wrap">
    <input {...input} id={id} type={password ? visible ? "text" : "password" : input.type}
      aria-invalid={!!error} aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined} />
    {password && <button type="button" className="auth-password-toggle" aria-label={`${visible ? "Hide" : "Show"} ${label.toLowerCase()}`} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? "hide" : "show"}</button>}</div>
    {hint && <p className="auth-hint" id={`${id}-hint`}>{hint}</p>}
    {error && <p className="auth-field-error" id={`${id}-error`}>{error}</p>}</div>;
}

export function useFormAction() {
  const [errors, setErrors] = useState<FieldErrors>({});
  const [state, setState] = useState<{ status: "idle" | "pending" | "success" | "error"; message?: string }>({ status: "idle" });
  const busy = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const submit = async (event: FormEvent<HTMLFormElement>, nextErrors: FieldErrors, action: () => Promise<string>) => {
    event.preventDefault();
    if (busy.current) return;
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      setState({ status: "error", message: "Check the highlighted fields and try again." });
      const input = Array.from(event.currentTarget.elements).find((element) => element instanceof HTMLInputElement && nextErrors[element.name as keyof FieldErrors]);
      if (input instanceof HTMLInputElement) input.focus();
      return;
    }
    busy.current = true;
    setState({ status: "pending" });
    try {
      const message = await action();
      if (mounted.current) setState({ status: "success", message });
    } catch (error) {
      if (mounted.current) setState({ status: "error", message: authErrorMessage(error) });
    } finally { busy.current = false; }
  };
  return { errors, state, submit, pending: state.status === "pending" };
}

export function FormMessage({ state }: { state: ReturnType<typeof useFormAction>["state"] }) {
  if (!state.message) return null;
  return <p className={`auth-message auth-message--${state.status}`} role={state.status === "error" ? "alert" : "status"}>{state.message}</p>;
}
