import { useState } from "react";
import { useAuth } from "./AuthProvider";
import { AuthField, AuthLink, AuthNotice, FormMessage, SocialButtons, useFormAction } from "./FormControls";
import type { AuthFormProps } from "./FormControls";
import { validateLogin } from "./validation";

export function LoginForm({ onNavigate }: AuthFormProps) {
  const { service, state } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const form = useFormAction();
  return <><AuthNotice /><form className="auth-form" noValidate aria-busy={form.pending} onSubmit={(event) => {
    void form.submit(event, validateLogin({ email, password }), async () => {
      await service.signIn({ email: email.trim(), password, rememberMe });
      // Provider confirmation is required before the UI claims sign-in.
      if (service.getSnapshot().status !== "signed-in") throw new Error("Session not confirmed");
      setPassword(""); return "You’re signed in. Your workspace is ready.";
    });
  }}><fieldset disabled={form.pending || state.status === "loading" || state.status === "signed-in"}>
      <AuthField label="Email address" name="email" type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} error={form.errors.email} />
      <AuthField label="Password" name="password" password autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} error={form.errors.password} />
      <div className="auth-options"><label><input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} />Remember me</label><AuthLink route="/forgot-password" onNavigate={onNavigate}>Forgot password?</AuthLink></div>
      <button className="auth-submit" type="submit">{form.pending ? "Logging in…" : "Log In"}<span aria-hidden="true">→</span></button>
    </fieldset><FormMessage state={form.state} /></form><SocialButtons />
    <p className="auth-switch">New to Page? <AuthLink route="/signup" onNavigate={onNavigate}>Create an account</AuthLink></p></>;
}
