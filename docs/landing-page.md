# Page download website

The landing page reuses the app's warm ivory, pale blue, and navy palette, defined
in `apps/desktop/src/palette.css` and shared across the frontend entry points.
Large sans-serif headlines, open spacing, a book-and-paper hero, and pill buttons
continue the visual direction inspired by notacareerfair.com. The copy, imagery,
and interactive graph are Page's own.

Content includes the mission (knowledge ownership and future source-attributed
context selection), a three-step explanation, an illustrative clickable graph,
native FAQ disclosures, and a dedicated download section. AI answers and context
optimization are described as future work, not available features. The graph demo
uses sample content; the real app's current graph lines represent shared collections.

## Preview and export

The frontend remains a Vite multi-page build used by Tauri. This web export does
not change the default desktop window or require a hosting SDK/service.

- `npm run dev`: landing page at `http://localhost:1420/landing.html`, graph preview
  at `/graph.html`, and the Stage 6 desktop editing interface at `/`.
- `npm run build`: TypeScript validation and Vite production assets.
- `npm run tauri:build -- --bundles app`: build the native macOS bundle.
- `npm run landing:export`: create `dist/page-website/`, including the app ZIP.
- `npm run landing:preview`: serve the export at `http://localhost:4173/`.

The export serves the landing page at `/`, graph workspace preview at `/app/`, and
account interfaces at `/login/`, `/signup/`, and `/forgot-password/`. Deploy the
contents of `dist/page-website/` to any static web host at its domain root. Configure
the host to serve directory `index.html` files and ZIP files as downloads. This
workflow does not publish anything automatically.

The exporter requires a real Apple Silicon `Page.app`, defaulting to
`apps/desktop/src-tauri/target/release/bundle/macos/Page.app`. Override its location
with `PAGE_MAC_APP=/absolute/path/Page.app npm run landing:export`. It checks the
bundle's executable architecture, archives the complete app with `ditto` (preserving
macOS bundle metadata), and writes:

- `downloads/Page-macos-arm64-<build-id>.zip` (the build ID comes from the archive's SHA-256)
- `downloads/manifest.json`: archive size, SHA-256, generation time, and platform.

Each different archive gets its own download URL to avoid reusing a cached
older build. The export updates the landing button and manifest to that archive.
Rebuild the desktop app before exporting when its frontend has changed. Exporting
uses the existing bundle; it does not compile Rust or install dependencies. Build
output and downloads are ignored by Git.

## Download behavior and current limits

The export adds `data-mac-download-url` to the landing page's root element. The
React component accepts this URL and shows a real download anchor. An unconfigured
landing page (including ordinary Vite development) shows an unavailable download
state rather than a broken link. Hero and navigation buttons always lead to the
download section. The export's macOS button points to the bundled ZIP.

This is an unnotarized **development** app for Apple Silicon. Unzip it to get
`Page.app`. The default native workspace uses the Stage 6 editing interface from
`main`. The sample graph remains a separate web preview. The Python core is not
included in the archive: native vault editing requires separate installation and
interpreter configuration as described in `docs/development.md`. The optional
graph ingestion service uses separate setup described in `docs/ingestion.md`.
Windows downloads are unavailable. Online authentication and AI answers remain
unconfigured. There is no automatic update or installer service.

The export includes compiled frontend assets and the native app, with no session
credentials, user notes, vault databases, or account secrets. Existing authentication
navigation remains accessible; browser workspace previews are illustrative and do
not connect to a visitor's local backend automatically.

Layouts adapt to mobile widths, focus styles and labels support keyboard use, and
motion respects reduced-motion preferences. Native/browser visual capture has not
been performed because capture authorization was unavailable in this session.
