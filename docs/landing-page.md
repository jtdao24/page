# Page landing page

Page has a separate marketing entry point alongside the workspace:

- `http://localhost:1420/landing.html`: landing page.
- `http://localhost:1420/`: bookshelf dashboard, also the default Tauri window.

Run `npm run dev` to preview both. `npm run build` produces `dist/index.html` and
`dist/landing.html` using Vite's multiple HTML entry points. Landing styles are
isolated in `apps/desktop/src/landing.css`; the dashboard styles are unchanged.

The direction adapts [notacareerfair.com](https://notacareerfair.com)'s white space,
oversized black sans-serif headlines, cutout hero and glossy orange CTA. Page's
copy, branding, interactive library example and generated book image are original.
The hero asset lives in `apps/desktop/src/assets/page-books.png` with transparency.

Calls-to-action open the existing workspace preview. They do not promise a finished
installer or working Gemini chat. The FAQ describes those features' actual status.
The sample bookshelf is interactive and explicitly illustrative. FAQ rows use
native keyboard-accessible disclosure controls. Layouts adapt to mobile, and
motion respects the visitor's reduced-motion preference.

## Private Sites publication

Private preview: [Page landing page](https://page-knowledge-workspace.richflea64.chatgpt.site).

The registered project is `appgprj_6ac9c757204481919490b6dadbcd809b`, with slug
`page-knowledge-workspace`. Its publication checkout is `sites/page-landing`,
ignored by the Page repository and versioned separately through the Sites workflow.
The hosting manifest in that checkout must retain this exact project ID.

Refresh its buildless snapshot after building the app:

```sh
npm run build
npm run landing:export
```

The snapshot serves the landing page at `/` and the workspace preview at `/app/`.
It includes compiled frontend assets and no Python backend, session credentials,
user notes, or vault databases. Hosted workspace preview shows the sample library;
the real local core connection is intended for the desktop/local development origin.

To resume publishing on another machine, use the existing Sites project and its
source-opening helper to retrieve the publication checkout, rather than creating
another Site. After export, run the Sites source workflow to push and package the
snapshot, then publish that exact commit/archive to the existing private Site.

Validation: TypeScript, ESLint, Vitest (4 tests), and the production build passed.
Both local and exported HTML entries resolve all linked build assets. The local
landing route returned HTTP 200 and the native Sites deployment completed
successfully. Visual browser inspection was unavailable because screen capture
permission was disabled; it has not been claimed as verified.
