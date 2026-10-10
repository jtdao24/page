import { useEffect, useState } from "react";
import type { ContextNote } from "./library";

export interface IndexStatus {
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

export const CORE_URL = "http://127.0.0.1:8765";

export function useCore() {
  const [session, setSession] = useState<string | null>(null);
  const [status, setStatus] = useState<IndexStatus | null>(null);
  const [notes, setNotes] = useState<ContextNote[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (!session) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      let running = false;
      try {
        const options = { headers: { Authorization: `Bearer ${session}` },
          signal: AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]) };
        const [statusResponse, notesResponse] = await Promise.all([
          fetch(`${CORE_URL}/api/index/status`, options), fetch(`${CORE_URL}/api/context`, options),
        ]);
        if (!statusResponse.ok || !notesResponse.ok) {
          throw new Error(statusResponse.status === 401 ? "That session token didn’t connect. Check it and try again."
            : "Couldn’t load your library. Make sure the local core service is running and up to date.");
        }
        const next = (await statusResponse.json()) as IndexStatus;
        const library = (await notesResponse.json()) as { notes: ContextNote[] };
        running = next.state === "running";
        if (!disposed) { setStatus(next); setNotes(library.notes); setError(null); }
      } catch (cause) {
        if (!disposed) setError(cause instanceof Error ? cause.message : "Couldn’t connect to your vault.");
      } finally {
        if (!disposed) timer = setTimeout(() => { void poll(); }, running ? 1000 : 4000);
      }
    };
    void poll();
    return () => { disposed = true; clearTimeout(timer); controller.abort(); };
  }, [session]);

  const connect = (token: string) => { setStatus(null); setNotes(null); setError(null); setSession(token.trim()); };
  const disconnect = () => { setSession(null); setStatus(null); setNotes(null); setError(null); };
  const index = async (rebuild: boolean) => {
    if (!session) return;
    setPending(true);
    try {
      const response = await fetch(`${CORE_URL}/api/index${rebuild ? "/rebuild" : ""}`, {
        method: "POST", headers: { Authorization: `Bearer ${session}` }, signal: AbortSignal.timeout(8000),
      });
      if (!response.ok && response.status !== 409) throw new Error(`Indexing request failed (${response.status})`);
      const next = (await response.json()) as IndexStatus;
      setStatus((previous) => ({ ...next, vault: previous?.vault ?? "Your vault" }));
      setError(null);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Indexing failed"); }
    finally { setPending(false); }
  };
  return { session, status, notes, error, pending, connect, disconnect, index };
}
