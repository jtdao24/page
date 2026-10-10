// Create a buildless Sites snapshot from the already-built Vite frontend.
// The editable source remains in apps/desktop/src/LandingPage.tsx and landing.css.
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const repository = fileURLToPath(new URL("../", import.meta.url));
const build = path.join(repository, "apps/desktop/dist");
const site = path.join(repository, "sites/page-landing");
const manifestPath = path.join(site, ".openai/hosting.json");
if (!existsSync(path.join(build, "landing.html"))) throw new Error("Run npm run build before exporting the landing page.");
if (!existsSync(manifestPath)) throw new Error("Open the existing Page Site checkout before exporting. See docs/landing-page.md.");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
if (!manifest.project_id) throw new Error("The Page Site project_id must be persisted before export.");
const output = path.join(site, "dist");
mkdirSync(output, { recursive: true });
cpSync(build, output, { recursive: true });
mkdirSync(path.join(output, "app"), { recursive: true });
cpSync(path.join(build, "index.html"), path.join(output, "app/index.html"));
const landing = readFileSync(path.join(build, "landing.html"), "utf8").replace('data-app-url="/"', 'data-app-url="/app/"');
writeFileSync(path.join(output, "index.html"), landing);
writeFileSync(path.join(output, "landing.html"), landing);
writeFileSync(manifestPath, JSON.stringify({ ...manifest, static: { ...manifest.static, directory: "dist" } }, null, 2) + "\n");
writeFileSync(path.join(site, ".gitignore"), "node_modules/\n.sites-runtime/\n.sites-checkout*/\n.DS_Store\n*.log\n");
writeFileSync(path.join(site, "README.md"), "# Page landing page\n\nBuildless publication snapshot of the Vite Page frontend. The landing page is at `/`; the workspace preview is at `/app/`.\n\nEditable source: https://github.com/jtdao24/page, in `apps/desktop/src/LandingPage.tsx` and `landing.css`. Refresh this snapshot from that checkout with `npm run build` followed by `npm run landing:export`. Publish through the Sites source workflow; preserve `.openai/hosting.json` and its project ID. No Python backend, credentials, or user vault data are included.\n");
console.log(`Prepared Page landing page snapshot at ${site}`);
