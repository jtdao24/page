import { useEffect, useState } from "react";

interface IndexStatus {
  vault: string;
  state: string;
  phase: string;
  completed: number;
  total: number;
  changed: number;
  skipped: number;
  embedded: number;
  reused: number;
  deleted: number;
  error: string | null;
}

const CORE_URL = "http://127.0.0.1:8765";

function App() {
  const [token, setToken] = useState("");
  const [session, setSession] = useState<string | null>(null);
  const [status, setStatus] = useState<IndexStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!session) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      try {
        const response = await fetch(`${CORE_URL}/api/index/status`, {
          headers: { Authorization: `Bearer ${session}` },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(`Connection failed (${response.status})`);
        const next = (await response.json()) as IndexStatus;
        if (!disposed) {
          setStatus(next);
          setError(null);
        }
      } catch (cause) {
        if (!disposed) setError(cause instanceof Error ? cause.message : "Connection failed");
      } finally {
        if (!disposed) timer = setTimeout(() => { void poll(); }, 1000);
      }
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); controller.abort(); };
  }, [session]);

  const index = async (rebuild: boolean) => {
    if (!session) return;
    setPending(true);
    try {
      const response = await fetch(`${CORE_URL}/api/index${rebuild ? "/rebuild" : ""}`, {
        method: "POST",
        headers: { Authorization: `Bearer ${session}` },
      });
      if (!response.ok) throw new Error(`Indexing request failed (${response.status})`);
      setStatus((await response.json()) as IndexStatus);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Indexing failed");
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 bg-white p-8 text-neutral-900">
      <h1 className="text-4xl font-semibold tracking-tight">Page</h1>
      <section aria-labelledby="index-heading" className="flex flex-col gap-4">
        <h2 id="index-heading" className="text-xl font-medium">Vault indexing</h2>
        <p>Connect to your local core service to index your Markdown vault.</p>
        <form className="flex flex-col gap-2" onSubmit={(event) => {
          event.preventDefault(); setStatus(null); setSession(token.trim());
        }}>
          <label htmlFor="session-token">Core session token</label>
          <input id="session-token" type="password" autoComplete="off" value={token}
            onChange={(event) => setToken(event.target.value)} className="rounded border p-2" />
          <button disabled={!token.trim()} className="rounded border p-2 disabled:opacity-50">Connect</button>
        </form>
        {status && <div role="status" aria-live="polite" className="flex flex-col gap-2">
          <p>{status.vault ? `${status.vault}: ` : ""}{status.state} {status.state === "running" ? `— ${status.phase}` : ""}</p>
          {status.state === "running" && <progress aria-label="Notes scanned"
            value={status.completed} max={Math.max(status.total, 1)} className="w-full" />}
          <p>{status.completed}/{status.total} notes scanned · {status.embedded} chunks embedded · {status.reused} cached vectors reused · {status.skipped} notes unchanged</p>
          <div className="flex gap-2">
            <button className="rounded border p-2 disabled:opacity-50" disabled={pending || status.state === "running"}
              onClick={() => { void index(false); }}>Index changes</button>
            <button className="rounded border p-2 disabled:opacity-50" disabled={pending || status.state === "running"}
              onClick={() => { void index(true); }}>Rebuild index</button>
          </div>
          {status.error && <p role="alert">{status.error}</p>}
        </div>}
        {error && <p role="alert">{error}</p>}
      </section>
    </main>
  );
}

export default App;
