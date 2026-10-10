// Export the landing page as a standalone static website. No hosting service required.
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repository = fileURLToPath(new URL("../", import.meta.url));
const build = path.join(repository, "apps/desktop/dist");
const output = path.join(repository, "dist/page-website");
const app = path.resolve(process.env.PAGE_MAC_APP ?? path.join(repository, "apps/desktop/src-tauri/target/release/bundle/macos/Page.app"));
if (!existsSync(path.join(build, "landing.html"))) throw new Error("Run npm run build before exporting the landing page.");
// Require a real supported bundle so the exported Download button cannot lead to a missing file.
const executable = path.join(app, "Contents/MacOS/page-desktop");
if (!existsSync(executable)) throw new Error("Build the macOS app first: npm run tauri:build -- --bundles app. Or set PAGE_MAC_APP to an existing Page.app.");
const architecture = execFileSync("file", [executable], { encoding: "utf8" });
if (!architecture.trim().endsWith("Mach-O 64-bit executable arm64")) throw new Error("This download is labeled Apple Silicon; export requires an arm64 Page.app.");
mkdirSync(output, { recursive: true });
cpSync(build, output, { recursive: true });
mkdirSync(path.join(output, "app"), { recursive: true });
cpSync(path.join(build, "index.html"), path.join(output, "app/index.html"));
const downloads = path.join(output, "downloads");
mkdirSync(downloads, { recursive: true });
const filename = "Page-macos-arm64.zip";
const archive = path.join(downloads, filename);
execFileSync("ditto", ["-c", "-k", "--sequesterRsrc", "--keepParent", app, archive]);
const bytes = readFileSync(archive);
writeFileSync(path.join(downloads, "manifest.json"), JSON.stringify({
  filename, platform: "macOS", architecture: "arm64", channel: "development",
  bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"),
  created_at: new Date().toISOString(), core_bundled: false,
}, null, 2) + "\n");
const landing = readFileSync(path.join(build, "landing.html"), "utf8")
  .replace('data-app-url="/"', `data-app-url="/app/" data-mac-download-url="/downloads/${filename}"`);
writeFileSync(path.join(output, "index.html"), landing);
writeFileSync(path.join(output, "landing.html"), landing);
console.log(`Static website ready at ${output}`);
console.log(`Included download: ${filename} (${(bytes.length / 1024 / 1024).toFixed(2)} MiB). Python core is installed separately.`);
console.log("Preview with: npm run landing:preview");
