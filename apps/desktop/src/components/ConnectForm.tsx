import { useState, type FormEvent } from "react";
import { ApiError, getIndexStatus, isUnauthorized, setApiToken } from "../api/client";

interface ConnectFormProps {
  onConnected: (token: string) => void;
  /** Shown above the form, for example after the API rejected a saved token. */
  notice?: string | null;
}

export default function ConnectForm({ onConnected, notice = null }: ConnectFormProps) {
  const [token, setToken] = useState("");
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const connect = async (event: FormEvent) => {
    event.preventDefault();
    const value = token.trim();
    if (!value) {
      return;
    }
    setChecking(true);
    setError(null);
    setApiToken(value);
    try {
      await getIndexStatus();
      onConnected(value);
    } catch (failure) {
      setApiToken(null);
      setError(
        isUnauthorized(failure)
          ? "That token was not accepted. Copy the token Page Core printed when it started."
          : failure instanceof ApiError
            ? failure.message
            : "Could not connect to Page Core.",
      );
    } finally {
      setChecking(false);
    }
  };

  return (
    <form onSubmit={connect} aria-label="Connect to Page Core" className="mx-auto mt-16 flex w-full max-w-md flex-col gap-3 px-4">
      <h2 className="text-base font-semibold">Connect to Page Core</h2>
      <p className="text-sm text-neutral-600">
        Start Page Core with <code className="rounded bg-neutral-100 px-1">python -m page_core.api --vault PATH</code> and
        paste the API token it prints.
      </p>
      {notice && <p className="text-sm text-amber-800">{notice}</p>}
      <label htmlFor="api-token" className="text-sm font-medium">
        API token
      </label>
      <input
        id="api-token"
        type="password"
        autoComplete="off"
        spellCheck={false}
        value={token}
        onChange={(event) => setToken(event.target.value)}
        className="rounded border border-neutral-300 px-2 py-1.5 font-mono text-sm focus:border-neutral-900 focus:outline-none"
      />
      <button
        type="submit"
        disabled={!token.trim() || checking}
        className="self-start rounded bg-neutral-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-neutral-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-900 disabled:opacity-40"
      >
        {checking ? "Connecting…" : "Connect"}
      </button>
      {error && (
        <p role="alert" className="text-sm text-rose-700">
          {error}
        </p>
      )}
    </form>
  );
}
