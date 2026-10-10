// Mirrors packages/core/src/page_core/api/schemas.py; keep the two in step.

export interface SemanticSearchRequest {
  query: string;
  limit?: number;
}

export interface ChunkLocation {
  /** Stable UUID of the chunk; kept across edits to other parts of the note. */
  id: string;
  ordinal: number;
  /** The chunk is the note's UTF-8 bytes [start_byte, end_byte). */
  start_byte: number;
  end_byte: number;
  heading: string | null;
}

export interface SemanticSearchHit {
  /** Persistent note ID; stable across restarts and across renames that keep the content. */
  note_id: string;
  path: string;
  title: string;
  /** Cosine similarity of the query and the best-matching chunk, in [-1, 1]. Not a probability. */
  score: number;
  excerpt: string;
  chunk: ChunkLocation;
  matched_chunks: number;
}

export interface SemanticSearchResponse {
  query: string;
  limit: number;
  metric: "cosine";
  model: string;
  /** Ranked by descending score, then by path; one entry per note. */
  results: SemanticSearchHit[];
}

export interface NoteResponse {
  /** Persistent note ID from the search index; null until the note is indexed. */
  id: string | null;
  path: string;
  title: string;
  content: string;
  updated_at: string;
}

export interface ErrorDetail {
  code: string;
  message: string;
}

export interface SyncReport {
  added: number;
  updated: number;
  moved: number;
  removed: number;
  unchanged: number;
  failed: string[];
}

export interface IndexStatusResponse {
  state: "loading" | "indexing" | "ready" | "error";
  searchable: boolean;
  detail: string | null;
  vault_name: string;
  model: string | null;
  dimension: number | null;
  metric: "cosine";
  notes: number;
  chunks: number;
  last_sync_at: string | null;
  last_sync: SyncReport | null;
}
