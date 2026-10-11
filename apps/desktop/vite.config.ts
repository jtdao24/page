import process from "node:process";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const host = process.env.TAURI_DEV_HOST;

// https://v2.tauri.app/start/frontend/vite/
export default defineConfig({
  plugins: [react(), tailwindcss(), {
    name: "page-local-installer",
    configureServer(server) {
      // Serve the installer separately: putting it in public/ would embed it
      // inside the native app every time Vite builds the frontend.
      const installer = fileURLToPath(new URL("./src-tauri/target/release/bundle/dmg/Page_0.1.0_aarch64.dmg", import.meta.url));
      server.middlewares.use((request, response, next) => {
        if (request.url?.split("?")[0] !== "/downloads/Page-0.1.0-macos-arm64.dmg") return next();
        void (async () => {
          if (request.method !== "GET" && request.method !== "HEAD") {
            response.writeHead(405, { Allow: "GET, HEAD" });
            response.end();
            return;
          }
          const info = await stat(installer);
          response.writeHead(200, {
            "Content-Type": "application/x-apple-diskimage",
            "Content-Length": String(info.size),
            "Content-Disposition": 'attachment; filename="Page-0.1.0-macos-arm64.dmg"',
            "Cache-Control": "no-store",
          });
          if (request.method === "HEAD") response.end();
          else createReadStream(installer).on("error", () => response.destroy()).pipe(response);
        })().catch(() => {
          response.writeHead(404, { "Content-Type": "text/plain" });
          response.end("Installer not built yet. Run npm run tauri:bundle.");
        });
      });
    },
  }],
  // Keep Rust errors visible in `tauri dev` output.
  clearScreen: false,
  build: {
    rollupOptions: {
      input: {
        app: fileURLToPath(new URL("./index.html", import.meta.url)),
        landing: fileURLToPath(new URL("./landing.html", import.meta.url)),
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
