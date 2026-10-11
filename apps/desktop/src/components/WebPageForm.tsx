import { useState } from "react";
import { type DesktopError, toDesktopError } from "../core/types";
import { ErrorText } from "./ErrorText";

/** Ask for a web address; the page is fetched once and saved as a note. */
export function WebPageForm({ onSubmit, onCancel }: { onSubmit: (url: string) => Promise<void>; onCancel: () => void }) {
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<DesktopError | null>(null);
  return <form className="web-page-form" onSubmit={(event) => {
    event.preventDefault();
    if (!url.trim() || busy) return;
    setBusy(true);
    setError(null);
    onSubmit(url.trim()).catch((cause: unknown) => { setError(toDesktopError(cause)); setBusy(false); });
  }}>
    <p>Page downloads the page once, keeps its readable text, and saves it as a Markdown note in
      <code> web/</code> with a link to the original. Search, Ask and the graph can then use it.</p>
    <label htmlFor="web-page-url">Web address</label>
    <input id="web-page-url" type="url" inputMode="url" autoFocus placeholder="https://example.com/article" value={url}
      disabled={busy} onChange={(event) => setUrl(event.target.value)} />
    {busy && <p role="status">Downloading and saving…</p>}
    {error && <p role="alert"><ErrorText error={error} /></p>}
    <div className="dialog-actions">
      <button type="submit" disabled={busy || !url.trim()}>Save Page</button>
      <button type="button" onClick={onCancel}>Cancel</button>
    </div>
  </form>;
}
