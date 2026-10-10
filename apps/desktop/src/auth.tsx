import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { AuthPage } from "./auth/AuthPage";
import { AuthProvider } from "./auth/AuthProvider";
import { authRouteTitle, resolveAuthRoute } from "./auth/routes";
import "./auth/auth.css";

const root = document.getElementById("root") as HTMLElement;
const route = resolveAuthRoute(window.location.pathname);
if (!route) throw new Error("Unknown authentication route");
document.title = authRouteTitle(route);
createRoot(root).render(<StrictMode><AuthProvider><AuthPage route={route} appHref={root.dataset.appUrl ?? "/"} homeHref={root.dataset.homeUrl ?? "/landing.html"} /></AuthProvider></StrictMode>);
