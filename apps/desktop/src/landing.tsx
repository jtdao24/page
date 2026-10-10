import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import LandingPage from "./LandingPage";
import "./landing.css";

const root = document.getElementById("root") as HTMLElement;
createRoot(root).render(<StrictMode><LandingPage appHref={root.dataset.appUrl ?? "/"} /></StrictMode>);
