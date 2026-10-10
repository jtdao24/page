import process from "node:process";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const host = process.env.TAURI_DEV_HOST;

// https://v2.tauri.app/start/frontend/vite/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Keep Rust errors visible in `tauri dev` output.
  clearScreen: false,
  build: {
    rollupOptions: {
      input: {
        app: fileURLToPath(new URL("./index.html", import.meta.url)),
        landing: fileURLToPath(new URL("./landing.html", import.meta.url)),
        login: fileURLToPath(new URL("./login/index.html", import.meta.url)),
        signup: fileURLToPath(new URL("./signup/index.html", import.meta.url)),
        forgotPassword: fileURLToPath(new URL("./forgot-password/index.html", import.meta.url)),
      },
    },
  },
  server: {
    // Tauri expects a fixed port; fail if it is unavailable.
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
