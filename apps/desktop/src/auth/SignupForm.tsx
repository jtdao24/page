import { useState } from "react";
import { useAuth } from "./AuthProvider";
import { AuthField, AuthLink, AuthNotice, FormMessage, SocialButtons, useFormAction } from "./FormControls";
import type { AuthFormProps } from "./FormControls";
import { validateSignup } from "./validation";

export function SignupForm({ onNavigate }: AuthFormProps) {
  const { service, state } = useAuth();
  const [input, setInput] = useState({ name: "", email: "", password: "", confirmPassword: "" });
  const form = useFormAction();
  const update = (field: keyof typeof input, value: string) => setInput((previous) => ({ ...previous, [field]: value }));
  return <><AuthNotice /><form className="auth-form" noValidate aria-busy={form.pending} onSubmit={(event) => {
    void form.submit(event, validateSignup(input), async () => {
      const result = await service.signUp({ name: input.name.trim(), email: input.email.trim(), password: input.password });
      if (result.status === "authenticated" && service.getSnapshot().status !== "signed-in") throw new Error("Session not confirmed");
      setInput((previous) => ({ ...previous, password: "", confirmPassword: "" }));
      return result.status === "verification-required" ? "Check your email to verify your account before signing in." : "Your account is ready. You’re signed in.";
    });
  }}><fieldset disabled={form.pending || state.status === "loading" || state.status === "signed-in"}>
      <AuthField label="Name" name="name" autoComplete="name" required maxLength={100} value={input.name} onChange={(event) => update("name", event.target.value)} error={form.errors.name} />
      <AuthField label="Email address" name="email" type="email" autoComplete="email" required value={input.email} onChange={(event) => update("email", event.target.value)} error={form.errors.email} />
      <AuthField label="Password" name="password" password autoComplete="new-password" required hint="Use 12–128 characters. Make it a phrase worth remembering." value={input.password} onChange={(event) => update("password", event.target.value)} error={form.errors.password} />
      <AuthField label="Confirm password" name="confirmPassword" password autoComplete="new-password" required value={input.confirmPassword} onChange={(event) => update("confirmPassword", event.target.value)} error={form.errors.confirmPassword} />
      <button className="auth-submit" type="submit">{form.pending ? "Creating account…" : "Create Account"}<span aria-hidden="true">→</span></button>
    </fieldset><FormMessage state={form.state} /></form><SocialButtons />
    <p className="auth-switch">Already have an account? <AuthLink route="/login" onNavigate={onNavigate}>Log In</AuthLink></p></>;
}
