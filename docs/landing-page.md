# Landing page and installer deployment

The editable landing page is `apps/desktop/src/LandingPage.tsx`. Run `npm run tauri:dev`
and open `http://localhost:1420/landing.html` to preview it. Vite serves the existing
DMG at `/downloads/Page-0.1.0-macos-arm64.dmg` without copying it into the native
frontend bundle.

Prepare a fresh app and publication folder:

```sh
.venv/bin/python apps/desktop/scripts/prepare_runtime.py --sign -
CI=true APPLE_SIGNING_IDENTITY=- npm run tauri:bundle
npm run landing:export
npm run landing:preview
```

Preview the exported page at `http://localhost:4173`. Upload the contents of
`dist/page-website/` to a static host at its domain root. The folder includes the
landing page, frontend assets, an installer named with its content hash, and a
SHA-256 checksum and release manifest in `downloads/`. The native app includes
Python Core and the offline embedding model; users do not install Python.
The browser workspace preview cannot access vaults without Tauri.

This workflow creates an **ad hoc signed, non-notarized** installer. It does not
publish a website or bypass Gatekeeper. For public distribution without a macOS
security exception, use Developer ID signing and notarization as described in
[packaging](packaging.md). Update the download copy and release manifest when a
notarized release replaces this build.
