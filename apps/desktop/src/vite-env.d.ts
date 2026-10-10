/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Page Core API. Defaults to http://127.0.0.1:8765. */
  readonly VITE_PAGE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
