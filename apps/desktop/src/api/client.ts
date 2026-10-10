import type { ErrorDetail, IndexStatusResponse, NoteResponse, SemanticSearchResponse } from "./types";

export const API_BASE: string = import.meta.env.VITE_PAGE_API_URL ?? "http://127.0.0.1:8765";

// The per-launch API token printed by Page Core. Kept in memory; App decides
// whether to remember it for the window session.
let apiToken: string | null = null;

export function setApiToken(token: string | null): void {
  apiToken = token;
}

/** A failed request. `status` is 0 when the API could not be reached at all. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...(apiToken ? { Authorization: `Bearer ${apiToken}` } : {}),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "unreachable", `Page Core is not reachable at ${API_BASE}.`);
  }
  if (!response.ok) {
    throw await toApiError(response);
  }
  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = ((await response.json()) as { detail?: unknown }).detail;
  } catch {
    detail = undefined;
  }
  if (detail && typeof detail === "object" && "code" in detail && "message" in detail) {
    const { code, message } = detail as ErrorDetail;
    return new ApiError(response.status, code, message);
  }
  if (response.status === 422) {
    return new ApiError(422, "invalid_request", "The search request was invalid.");
  }
  return new ApiError(response.status, "http_error", `Request failed with status ${response.status}.`);
}

export function isUnauthorized(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}

export function getIndexStatus(signal?: AbortSignal): Promise<IndexStatusResponse> {
  return request("/api/index/status", { signal });
}

export function semanticSearch(
  query: string,
  limit = 10,
  signal?: AbortSignal,
): Promise<SemanticSearchResponse> {
  return request("/api/search/semantic", {
    method: "POST",
    body: JSON.stringify({ query, limit }),
    signal,
  });
}

export function getNote(path: string, signal?: AbortSignal): Promise<NoteResponse> {
  return request(`/api/note?path=${encodeURIComponent(path)}`, { signal });
}
