import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AuthProvider } from "./auth/AuthProvider";
import { AuthPage } from "./auth/AuthPage";
import { authRouteTitle, resolveAuthRoute } from "./auth/routes";
import "./index.css";

// Tauri's asset server can fall back to index.html for a clean URL. Resolve
// auth paths here too, so that fallback still opens the requested interface.
const authRoute = resolveAuthRoute(window.location.pathname);
if (authRoute) document.title = authRouteTitle(authRoute);
createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <AuthProvider>{authRoute ? <AuthPage route={authRoute} /> : <App />}</AuthProvider>
  </StrictMode>,
);
