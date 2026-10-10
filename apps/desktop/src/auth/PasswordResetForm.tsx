import { useState } from "react";
import { useAuth } from "./AuthProvider";
import { AuthField, AuthLink, AuthNotice, FormMessage, useFormAction } from "./FormControls";
import type { AuthFormProps } from "./FormControls";
import { validatePasswordReset } from "./validation";

export function PasswordResetForm({ onNavigate }: AuthFormProps) {
  const { service, state } = useAuth();
  const [email, setEmail] = useState("");
  const form = useFormAction();
  return <><AuthNotice /><form className="auth-form" noValidate aria-busy={form.pending} onSubmit={(event) => {
    void form.submit(event, validatePasswordReset(email), async () => {
      await service.requestPasswordReset(email.trim());
      return "If an account exists for that address, you’ll receive a reset link. Check your inbox.";
    });
  }}><fieldset disabled={form.pending || state.status === "loading"}>
      <AuthField label="Email address" name="email" type="email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} error={form.errors.email} />
      <button className="auth-submit" type="submit">{form.pending ? "Sending reset link…" : "Send Reset Link"}<span aria-hidden="true">→</span></button>
    </fieldset><FormMessage state={form.state} /></form>
    <p className="auth-switch"><AuthLink route="/login" onNavigate={onNavigate}>← Return to Login</AuthLink></p></>;
}
