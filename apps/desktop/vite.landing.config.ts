import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// The landing page is a separate static site, built on its own so none of it
// (three.js, GSAP, marketing images) ends up inside the desktop app.
const landingAsIndex: Plugin = {
  name: "landing-as-index",
  enforce: "post",
  generateBundle(_options, bundle) {
    const page = bundle["landing.html"];
    if (page) page.fileName = "index.html";
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), landingAsIndex],
  build: {
    outDir: "dist-landing",
    emptyOutDir: true,
    rollupOptions: { input: fileURLToPath(new URL("./landing.html", import.meta.url)) },
  },
  preview: { port: 4173, strictPort: true },
});
