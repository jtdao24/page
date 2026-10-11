import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import LandingPage from "./LandingPage";
import "./landing.css";

const root = document.getElementById("root") as HTMLElement;
// A download link appears only when the page is published with a real build URL.
createRoot(root).render(<StrictMode><LandingPage macDownloadUrl={root.dataset.macDownloadUrl} /></StrictMode>);
