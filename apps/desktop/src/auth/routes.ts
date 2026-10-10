export const AUTH_ROUTES = ["/login", "/signup", "/forgot-password"] as const;
export type AuthRoute = typeof AUTH_ROUTES[number];

export function authRouteTitle(route: AuthRoute): string {
  return `${route === "/login" ? "Log In" : route === "/signup" ? "Sign Up" : "Reset password"} — Page`;
}

export function resolveAuthRoute(path: string): AuthRoute | null {
  const normalized = path.replace(/\/index\.html$/, "").replace(/\/$/, "");
  return AUTH_ROUTES.find((route) => route === normalized) ?? null;
}
