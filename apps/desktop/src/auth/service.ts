export interface AuthUser {
  id: string;
  name: string;
  email: string;
}

export type AuthState =
  | { status: "unconfigured" }
  | { status: "loading" }
  | { status: "signed-out" }
  | { status: "signed-in"; user: AuthUser }
  | { status: "error"; message: string };

export interface LoginInput { email: string; password: string; rememberMe: boolean }
export interface SignupInput { name: string; email: string; password: string }
export type SignupResult = { status: "verification-required" } | { status: "authenticated" };
export type ConnectedProvider = "google" | "github";

/** A provider owns session verification, persistence, and OAuth redirects.
 * Never mark a session signed-in based only on submitted form values. */
export interface AuthService {
  getSnapshot(): AuthState;
  subscribe(listener: () => void): () => void;
  signIn(input: LoginInput): Promise<void>;
  signUp(input: SignupInput): Promise<SignupResult>;
  requestPasswordReset(email: string): Promise<void>;
  signOut(): Promise<void>;
}

export class AuthUnavailableError extends Error {
  constructor() {
    super("Sign-in is not yet available. Your local workspace is ready to use without an account.");
    this.name = "AuthUnavailableError";
  }
}

const unavailableState: AuthState = Object.freeze({ status: "unconfigured" });
const unavailable = async (): Promise<never> => { throw new AuthUnavailableError(); };

// No network calls, credential storage, or invented sessions.
export const unconfiguredAuthService: AuthService = {
  getSnapshot: () => unavailableState,
  subscribe: () => () => {},
  signIn: unavailable,
  signUp: unavailable,
  requestPasswordReset: unavailable,
  signOut: unavailable,
};

export function authStatusLabel(state: AuthState): string {
  switch (state.status) {
    case "unconfigured": return "Sign-in not available";
    case "loading": return "Checking account…";
    case "signed-out": return "Not signed in";
    case "signed-in": return state.user.name || state.user.email;
    case "error": return "Account unavailable";
  }
}

export function authErrorMessage(error: unknown): string {
  if (error instanceof AuthUnavailableError) return error.message;
  // Providers should map errors to safe UI messages internally. Never display
  // arbitrary responses that could contain credentials or provider internals.
  return "We couldn’t complete that request. Please try again.";
}
