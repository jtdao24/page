import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { cp, mkdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const desktop = path.join(root, "apps/desktop");
const frontend = path.join(desktop, "dist");
const output = path.join(root, "dist/page-website");
const installer = path.join(desktop, "src-tauri/target/release/bundle/dmg/Page_0.1.0_aarch64.dmg");

// Validate inputs before replacing an existing publication folder.
const [html, info, appHtml] = await Promise.all([
  readFile(path.join(frontend, "landing.html"), "utf8"), stat(installer),
  readFile(path.join(frontend, "index.html"), "utf8"), stat(path.join(frontend, "assets")),
]);
if (!info.isFile() || info.size === 0) throw new Error("Build the DMG with npm run tauri:bundle first.");
if (!html.includes('data-mac-download-url="')) throw new Error("Rebuild the current frontend before exporting.");
const hash = createHash("sha256");
for await (const bytes of createReadStream(installer)) hash.update(bytes);
const sha256 = hash.digest("hex");
const filename = `Page-0.1.0-macos-arm64-${sha256.slice(0, 12)}.dmg`;
const downloadUrl = `./downloads/${filename}`;
await rm(output, { recursive: true, force: true });
await mkdir(path.join(output, "downloads"), { recursive: true });
await mkdir(path.join(output, "app"));
await cp(path.join(frontend, "assets"), path.join(output, "assets"), { recursive: true });
await writeFile(path.join(output, "app/index.html"), appHtml);
await cp(installer, path.join(output, "downloads", filename));
const landing = html.replace(/data-mac-download-url="[^"]*"/, `data-mac-download-url="${downloadUrl}"`)
  .replace(/data-app-url="[^"]*"/, 'data-app-url="./app/"');
await writeFile(path.join(output, "index.html"), landing);
await writeFile(path.join(output, "landing.html"), landing);
await writeFile(path.join(output, "downloads", `${filename}.sha256`), `${sha256}  ${filename}\n`);
await writeFile(path.join(output, "downloads/release.json"), JSON.stringify({
  version: "0.1.0", platform: "macOS", architecture: "arm64", minimumOS: "14.0",
  file: filename, bytes: info.size, sha256, signing: "ad-hoc", notarized: false,
}, null, 2) + "\n");
console.log(`Upload ${output} to a static host at its domain root.`);
console.log(`Installer: ${filename} (${(info.size / 1024 ** 2).toFixed(1)} MiB)`);
console.log(`SHA-256: ${sha256}`);
