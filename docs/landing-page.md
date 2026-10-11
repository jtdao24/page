# Landing page

The product landing page is a separate static site. Its source is
`apps/desktop/landing.html` and `apps/desktop/src/LandingPage.tsx` (with
`src/landing/` and `src/landing.css`). It's built with its own Vite config,
`apps/desktop/vite.landing.config.ts`, so none of it ships inside the desktop app.

## Preview and build

```sh
npm run dev                 # then open http://localhost:1420/landing.html (live reload)
npm run landing:build       # static site in apps/desktop/dist-landing/ (index.html + assets)
npm run landing:preview     # serve that build at http://localhost:4173
```

## Deploy

The repository root has configs for both hosts. Each runs `npm ci` and
`npm run landing:build` and publishes `apps/desktop/dist-landing`.

- **Vercel** (`vercel.json`): on vercel.com, choose **Add New → Project**, import
  `jtdao24/page`, and keep the defaults. The settings come from `vercel.json`. Every push
  to `main` redeploys, and pull requests get preview links.
- **Netlify** (`netlify.toml`): on netlify.com, choose **Add new site → Import an existing
  project**, pick the repository, and deploy. The build settings come from `netlify.toml`.

No environment variables or secrets are needed. Add a custom domain in the host's
dashboard.

## Download

Until a signed, Apple-notarized build exists, the download card and the nav button
say **Coming soon** and link to GitHub. To offer a build, publish it somewhere that
takes large files (the DMG is about 370 MB; a GitHub Release works), then set its URL
on the root element in `landing.html`:

```html
<div id="root" data-mac-download-url="https://github.com/jtdao24/page/releases/download/v0.1.0/Page-0.1.0-macos-arm64.dmg"></div>
```

The page then shows a **Download for macOS** button. Only link a notarized build:
macOS blocks unsigned apps downloaded from the web.

## Performance numbers

The performance section reads `benchmarks/results/landing-performance.json`, a copy of
the [evaluation](evaluation.md) report, and links to it for download. Regenerate the
report before changing the numbers on the page.
