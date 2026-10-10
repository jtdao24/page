import type { Backlink, GraphData, Note, NoteSummary } from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8765";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function health(): Promise<{ status: string }> {
  return request("/api/health");
}

export function listNotes(): Promise<NoteSummary[]> {
  return request("/api/notes");
}

export function getNote(id: string): Promise<Note> {
  return request(`/api/note?id=${encodeURIComponent(id)}`);
}

export function createNote(title: string, content = ""): Promise<Note> {
  return request("/api/notes", {
    method: "POST",
    body: JSON.stringify({ title, content }),
  });
}

export function updateNote(id: string, content: string, title?: string): Promise<Note> {
  return request(`/api/note?id=${encodeURIComponent(id)}`, {
    method: "PUT",
    body: JSON.stringify({ content, title: title ?? null }),
  });
}

export function deleteNote(id: string): Promise<void> {
  return request(`/api/note?id=${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function getBacklinks(id: string): Promise<Backlink[]> {
  return request(`/api/note/backlinks?id=${encodeURIComponent(id)}`);
}

export function getGraph(): Promise<GraphData> {
  return request("/api/graph");
}
