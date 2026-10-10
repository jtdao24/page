import { useAuth } from "./AuthProvider";
import { AuthLayout } from "./AuthLayout";
import { LoginForm } from "./LoginForm";
import { SignupForm } from "./SignupForm";
import { PasswordResetForm } from "./PasswordResetForm";
import type { AuthFormProps } from "./FormControls";
import type { AuthRoute } from "./routes";

export const authPageCopy = {
  "/login": { title: "welcome back", subtitle: "An account for future preferences, connected services, and sync." },
  "/signup": { title: "a new chapter", subtitle: "Your knowledge stays local. An account will connect the rest." },
  "/forgot-password": { title: "let’s start again", subtitle: "Enter your email and we’ll help you find your way back." },
};

export function AuthContent({ route, onNavigate, onContinue, appHref = "/" }: AuthFormProps & { route: AuthRoute }) {
  const { state } = useAuth();
  if (state.status === "signed-in") return <div className="auth-session"><p role="status">Signed in as <strong>{state.user.name || state.user.email}</strong>.</p>{onContinue ? <button className="auth-submit" onClick={onContinue}>Open App →</button> : <a className="auth-submit" href={appHref}>Open App →</a>}</div>;
  switch (route) {
    case "/login": return <LoginForm onNavigate={onNavigate} />;
    case "/signup": return <SignupForm onNavigate={onNavigate} />;
    case "/forgot-password": return <PasswordResetForm onNavigate={onNavigate} />;
  }
}

export function AuthPage({ route, appHref, homeHref }: { route: AuthRoute; appHref?: string; homeHref?: string }) {
  return <AuthLayout {...authPageCopy[route]} appHref={appHref} homeHref={homeHref}><AuthContent route={route} appHref={appHref} /></AuthLayout>;
}
