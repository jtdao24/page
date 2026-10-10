// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "./AuthProvider";
import { AuthPage } from "./AuthPage";
import { LoginForm } from "./LoginForm";
import { SignupForm } from "./SignupForm";
import { PasswordResetForm } from "./PasswordResetForm";
import { AccountSettings } from "./AccountSettings";
import { unconfiguredAuthService } from "./service";
import type { AuthService, AuthState } from "./service";
import { resolveAuthRoute } from "./routes";
import { validateLogin, validatePasswordReset, validateSignup } from "./validation";
import LandingPage from "../LandingPage";
import App from "../App";

afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

// Test-only provider fixture. The production app uses the rejecting,
// unconfigured service until a secure provider is supplied.
function testService(overrides: Partial<AuthService> = {}): AuthService {
  const state: AuthState = { status: "signed-out" };
  return { ...unconfiguredAuthService, getSnapshot: () => state, ...overrides };
}

describe("authentication boundary", () => {
  it("rejects every operation without network access or a fabricated session", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    const input = { email: "reader@example.com", password: "a test-only passphrase", rememberMe: true };
    await expect(unconfiguredAuthService.signIn(input)).rejects.toThrow("not yet available");
    await expect(unconfiguredAuthService.signUp({ ...input, name: "Reader" })).rejects.toThrow("not yet available");
    await expect(unconfiguredAuthService.requestPasswordReset(input.email)).rejects.toThrow("not yet available");
    await expect(unconfiguredAuthService.signOut()).rejects.toThrow("not yet available");
    expect(unconfiguredAuthService.getSnapshot()).toEqual({ status: "unconfigured" });
    expect(fetch).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
  });
  it("resolves direct, directory, and static auth routes only", () => {
    for (const route of ["/login", "/signup", "/forgot-password"] as const) {
      expect(resolveAuthRoute(route)).toBe(route);
      expect(resolveAuthRoute(`${route}/`)).toBe(route);
      expect(resolveAuthRoute(`${route}/index.html`)).toBe(route);
    }
    expect(resolveAuthRoute("/not-login")).toBeNull();
    expect(resolveAuthRoute("/app/login")).toBeNull();
  });
});

describe("client validation", () => {
  it("checks email and required login password without applying signup policy to an existing password", () => {
    expect(validateLogin({ email: "nope", password: "" })).toHaveProperty("email");
    expect(validateLogin({ email: "reader@example.com", password: "short" })).toEqual({});
    expect(validatePasswordReset(" ")).toHaveProperty("email");
    expect(validatePasswordReset("reader@ example.com")).toHaveProperty("email");
    expect(validatePasswordReset(" reader@example.com ")).toEqual({});
  });
  it("checks signup name, password length, and confirmation", () => {
    const input = { name: "Reader", email: "reader@example.com", password: "a test passphrase", confirmPassword: "a test passphrase" };
    expect(validateSignup(input)).toEqual({});
    expect(validateSignup({ ...input, name: " " })).toHaveProperty("name");
    expect(validateSignup({ ...input, password: "short" })).toHaveProperty("password");
    expect(validateSignup({ ...input, password: "x".repeat(129) })).toHaveProperty("password");
    expect(validateSignup({ ...input, confirmPassword: "different" })).toHaveProperty("confirmPassword");
  });
});

describe("auth form interactions", () => {
  it("focuses invalid fields, labels errors, and supports keyboard password toggling", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.click(screen.getByRole("button", { name: "Log In" }));
    expect(document.activeElement).toBe(screen.getByLabelText("Email address"));
    expect(screen.getByText("Enter your email address.").id).toBe(screen.getByLabelText("Email address").getAttribute("aria-describedby"));
    const toggle = screen.getByRole("button", { name: "Show password" });
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByLabelText("Password").getAttribute("type")).toBe("text");
    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(screen.getByLabelText("Password").getAttribute("type")).toBe("password");
  });
  it("validates credentials but never signs in with an unconfigured provider", async () => {
    const user = userEvent.setup();
    render(<LoginForm />);
    await user.type(screen.getByLabelText("Email address"), "reader@example.com");
    await user.type(screen.getByLabelText("Password"), "a test passphrase");
    await user.click(screen.getByLabelText("Remember me"));
    await user.click(screen.getByRole("button", { name: "Log In" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("not yet available"));
    expect(unconfiguredAuthService.getSnapshot().status).toBe("unconfigured");
    expect(localStorage.length).toBe(0);
    expect((screen.getByRole("button", { name: "Continue with Google" }) as HTMLButtonElement).disabled).toBe(true);
  });
  it("does not claim login success unless the provider confirms a real session", async () => {
    const signIn = vi.fn().mockResolvedValue(undefined);
    render(<AuthProvider service={testService({ signIn })}><LoginForm /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a test passphrase" } });
    fireEvent.click(screen.getByRole("button", { name: "Log In" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("You’re signed in. Your workspace is ready.")).toBeNull();
  });
  it("blocks mismatched passwords before the signup provider is called", async () => {
    const signUp = vi.fn();
    render(<AuthProvider service={testService({ signUp })}><SignupForm /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Reader" } });
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "a test passphrase" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "a different phrase" } });
    fireEvent.click(screen.getByRole("button", { name: "Create Account" }));
    expect(screen.getByText("Your passwords don’t match.")).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText("Confirm password"));
    expect(signUp).not.toHaveBeenCalled();
  });
  it("handles provider-required email verification without claiming a session", async () => {
    const signUp = vi.fn().mockResolvedValue({ status: "verification-required" });
    render(<AuthProvider service={testService({ signUp })}><SignupForm /></AuthProvider>);
    for (const [label, value] of [["Name", " Reader "], ["Email address", " reader@example.com "], ["Password", "a test passphrase"], ["Confirm password", "a test passphrase"]]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Create Account" }));
    expect(await screen.findByRole("status")).toHaveProperty("textContent", expect.stringContaining("verify your account"));
    expect(signUp).toHaveBeenCalledWith({ name: "Reader", email: "reader@example.com", password: "a test passphrase" });
    expect((screen.getByLabelText("Password") as HTMLInputElement).value).toBe("");
  });
  it("shows reset loading and confirmed success, and prevents duplicate submissions", async () => {
    let finish: () => void = () => {};
    const requestPasswordReset = vi.fn(() => new Promise<void>((resolve) => { finish = resolve; }));
    render(<AuthProvider service={testService({ requestPasswordReset })}><PasswordResetForm /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "reader@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Reset Link" }));
    expect(screen.getByRole("button", { name: "Sending reset link…" }).matches(":disabled")).toBe(true);
    fireEvent.submit(screen.getByLabelText("Email address").closest("form")!);
    expect(requestPasswordReset).toHaveBeenCalledTimes(1);
    await act(async () => { finish(); });
    expect(screen.getByRole("status").textContent).toContain("If an account exists");
  });
  it("shows reset provider errors without exposing raw details or claiming an email was sent", async () => {
    const requestPasswordReset = vi.fn().mockRejectedValue(new Error("private provider response"));
    render(<AuthProvider service={testService({ requestPasswordReset })}><PasswordResetForm /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Email address"), { target: { value: "reader@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send Reset Link" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("Please try again"));
    expect(screen.queryByText(/private provider response|If an account exists/)).toBeNull();
  });
});

describe("navigation and local workspace", () => {
  it("offers landing authentication and a direct workspace link", () => {
    render(<LandingPage appHref="/app/" />);
    expect(screen.getByRole("link", { name: "Log In" }).getAttribute("href")).toBe("/login/");
    expect(screen.getByRole("link", { name: "Sign Up" }).getAttribute("href")).toBe("/signup/");
    expect(screen.getByRole("link", { name: "Open App" }).getAttribute("href")).toBe("/app/");
  });
  it("provides all auth pages with navigation and an account-free workspace exit", () => {
    for (const route of ["/login", "/signup", "/forgot-password"] as const) {
      const view = render(<AuthPage route={route} appHref="/app/" homeHref="/" />);
      expect(screen.getByRole("link", { name: "Open App" }).getAttribute("href")).toBe("/app/");
      expect(screen.getByText("Sign-in is not yet available.")).toBeTruthy();
      expect(screen.getByRole("link", { name: "Continue to your workspace →" })).toBeTruthy();
      view.unmount();
    }
  });
  it("reflects verified account status and performs logout through the provider", async () => {
    let state: AuthState = { status: "signed-in", user: { id: "test-user", name: "Test Reader", email: "reader@example.com" } };
    let listener = () => {};
    const signOut = vi.fn(async () => { state = { status: "signed-out" }; listener(); });
    const service = testService({ getSnapshot: () => state, subscribe: (next) => { listener = next; return () => {}; }, signOut });
    render(<AuthProvider service={service}><AccountSettings onNavigate={vi.fn()} /></AuthProvider>);
    expect(screen.getByRole("heading", { name: "Test Reader" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Log Out" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("Not signed in"));
    expect(signOut).toHaveBeenCalledOnce();
  });
  it("opens account forms inside the workspace and returns without an authentication gate", async () => {
    // jsdom doesn't implement native modal dialogs. Focus trapping/Escape are
    // supplied by showModal in the browser and need a real browser check.
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
    const user = userEvent.setup();
    render(<App />);
    expect(screen.getByRole("heading", { name: "Your library." })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Profile and account settings" }));
    expect(screen.getByRole("heading", { name: "Workspace settings" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Log In" }));
    await user.click(screen.getByRole("link", { name: "Create an account" }));
    expect(screen.getByRole("heading", { name: "a new chapter" })).toBeTruthy();
    await user.click(screen.getByRole("link", { name: "Log In" }));
    await user.click(screen.getByRole("link", { name: "Forgot password?" }));
    expect(screen.getByRole("button", { name: "Send Reset Link" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Continue to local workspace →" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("heading", { name: "Your library." })).toBeTruthy();
  });
  it("keeps a connected vault and its in-memory token while navigating account forms", async () => {
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value: function(this: HTMLDialogElement) { this.setAttribute("open", ""); } });
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const body = String(input).endsWith("/api/context") ? { notes: [] } : {
        vault: "Test local vault", state: "idle", phase: "idle", completed: 0,
        total: 0, changed: 0, skipped: 0, embedded: 0, reused: 0, deleted: 0, error: null,
      };
      return new Response(JSON.stringify(body), { status: 200 });
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Vault settings" }));
    await user.type(screen.getByLabelText("Core session token"), "test-only-local-vault-token");
    await user.click(screen.getByRole("button", { name: "Connect vault" }));
    await screen.findByText("Your vault is connected.");
    await user.click(screen.getByRole("button", { name: "Account" }));
    await user.click(screen.getByRole("button", { name: "Log In" }));
    await user.click(screen.getByRole("link", { name: "Create an account" }));
    await user.click(screen.getByRole("button", { name: "Continue to local workspace →" }));
    expect(screen.getByText("Connected to your vault")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Vault settings" }));
    expect((screen.getByLabelText("Core session token") as HTMLInputElement).value).toBe("test-only-local-vault-token");
    await user.click(screen.getByRole("button", { name: "Index changes" }));
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:8765/api/index", expect.objectContaining({ headers: { Authorization: "Bearer test-only-local-vault-token" } })));
    expect(localStorage.length).toBe(0);
  });
});
