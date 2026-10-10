import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import GraphWorkspace from "./GraphWorkspace";
import { AuthProvider } from "./auth/AuthProvider";
import "./graph-index.css";

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode><AuthProvider><GraphWorkspace /></AuthProvider></StrictMode>,
);
