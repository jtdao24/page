# Account interfaces in the Tauri 2 desktop app

Page's local workspace does not require an online account. The authentication
foundation is part of the existing React/Vite frontend bundled by Tauri 2; it
does not add a backend, remote hosting dependency, or a replacement application.
The product continues to use its established Page branding.

## Navigation

The landing page at `/landing.html` provides **Log In**, **Sign Up**, and **Open
App** links. `/login`, `/signup`, and `/forgot-password` are separate Vite HTML
entries, with directory index files included in the packaged frontend. These
pages work without a server-side SPA rewrite. The main entry also resolves clean
auth URLs when Vite or Tauri falls back to the workspace index. Each has an exit to the local
workspace, which remains the default Tauri window at `/`.

In the desktop workspace, **Profile & account** opens settings. The **Vault**
and **Account** sections share the existing native dialog. Login, signup, and
reset forms open within that dialog, preserving the mounted workspace, its
in-memory vault token, indexing polling, and draft. Closing or cancelling a
dialog returns to the workspace without requiring authentication.

## Provider boundary

`src/auth/service.ts` defines `AuthService`, `AuthState`, profile information,
login and signup inputs, and signup outcomes. `AuthProvider` accepts a service
and subscribes to its state through React's `useSyncExternalStore`. A provider
must return a cached snapshot until its state changes and notify subscribers
after a verified session change. The default `unconfiguredAuthService` rejects
every account operation. It performs no network requests, credential storage,
or simulated login. Replace the service supplied to `AuthProvider` in both
desktop and standalone auth entry points when a secure provider is available.

The provider owns session verification and persistence. The **Remember me**
choice is passed to it; the UI does not save passwords or create tokens. Login
and account-creation success require provider confirmation. Signup can instead
report that email verification is required. Reset success appears only after
the provider resolves its request, and uses wording that doesn't reveal whether
an email address has an account. Raw provider errors are not shown to users.

The local vault service's bearer token is separate from user authentication.
It is not an online account or a cross-device session. Existing core APIs and
Stage 2–4 storage/indexing behavior are unchanged.

## Forms and unfinished services

`AuthLayout`, `LoginForm`, `SignupForm`, and `PasswordResetForm` are reusable.
They share Page's black editorial typography, white space, and orange actions.
Forms have associated labels, field errors, keyboard controls, password
visibility toggles, pending states, and live success/error messages. Invalid
submissions focus the first invalid field. Signup currently requires a name,
valid email, a matching confirmation, and a 12–128 character password; align
that policy with the future provider. Existing login passwords are not subject
to the new-account minimum.

Google/GitHub buttons are disabled and labeled as unconnected placeholders.
Settings expose profile details when supplied by a verified provider, login and
logout controls, and explicit future states for profile editing, connected
accounts, and sync. The frontend doesn't upload vaults or claim those future
features work. With the current service, submitting a valid form displays that
sign-in is not yet available.

## Development and verification

Use `npm run tauri:dev` to run the desktop app and `npm run tauri:build` to package
it. These require the Rust/Cargo toolchain and macOS build prerequisites. Vite
browser development is available through `npm run dev` for frontend work.

Run `npm run typecheck`, `npm run lint`, `npm run test`, and `npm run build` for
frontend checks. Auth tests use jsdom and Testing Library only as development
dependencies. They cover validation, password toggles, unavailable auth,
provider-confirmed outcomes, loading/error states, duplicate request prevention,
route resolution, settings navigation, and workspace access without an account.
They also verify that an active vault connection survives account-dialog navigation.
Native dialog focus trapping and full Tauri navigation require desktop UI QA;
jsdom's dialog stub is not a substitute for that check.

Validation on macOS: all 20 frontend tests passed, along with TypeScript,
ESLint, the production Vite build, and local HTTP checks of the auth entries.
All five built HTML entries resolved their referenced local assets. A Tauri 2
release build produced both `Page.app` and an Apple Silicon macOS DMG. Visual
desktop inspection was unavailable because screen capture was disabled; native
dialog behavior and responsive layout have not been visually verified.
