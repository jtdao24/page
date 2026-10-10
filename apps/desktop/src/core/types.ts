// Wire types shared with the Rust commands. Field names and meanings match
// page_core/api/schemas.py; timestamps stay strings and revisions are opaque.

export type Lifecycle = "stopped" | "starting" | "ready" | "failed" | "stopping";

export type ErrorKind = "api" | "transport" | "protocol" | "backend" | "preferences";

export interface DesktopError {
  kind: ErrorKind;
  status: number | null;
  code: string;
  message: string;
  details: Record<string, unknown> | null;
}

export interface BackendStatus {
  state: Lifecycle;
  generation: number;
  core_version: string | null;
  error: DesktopError | null;
}

export interface VaultResponse {
  id: string;
  name: string;
  root_path: string;
  needs_reconciliation: boolean;
}

export interface NoteSummaryResponse {
  id: string;
  vault_id: string;
  relative_path: string;
  created_at: string;
  updated_at: string;
  revision: string;
}

export interface NoteResponse extends NoteSummaryResponse {
  content: string;
}

export interface ReconcileResponse {
  added: number;
  modified: number;
  renamed: number;
  missing: number;
  unchanged: number;
}

export interface RecentVault {
  vault_id: string;
  root_path: string;
  last_note_id: string | null;
}

export interface DesktopPreferences {
  version: 1;
  recent_vaults: RecentVault[];
  active_vault_id: string | null;
}

/** A mutation that may have reached Page Core; storage may have changed. */
export const OUTCOME_UNKNOWN = "mutation_outcome_unknown";

export const MAX_RECENT_VAULTS = 10;

export function emptyPreferences(): DesktopPreferences {
  return { version: 1, recent_vaults: [], active_vault_id: null };
}

const KINDS: readonly string[] = ["api", "transport", "protocol", "backend", "preferences"];

export function isDesktopError(value: unknown): value is DesktopError {
  if (typeof value !== "object" || value === null) return false;
  const error = value as Record<string, unknown>;
  return (
    typeof error.kind === "string" &&
    KINDS.includes(error.kind) &&
    (error.status === null || typeof error.status === "number") &&
    typeof error.code === "string" &&
    typeof error.message === "string" &&
    (error.details === null || (typeof error.details === "object" && !Array.isArray(error.details)))
  );
}

/** Any rejection becomes a safe DesktopError; unknown values are never shown. */
export function toDesktopError(value: unknown): DesktopError {
  if (isDesktopError(value)) return value;
  return {
    kind: "protocol",
    status: null,
    code: "unexpected_failure",
    message: "The desktop bridge returned an unexpected failure.",
    details: null,
  };
}

export function isOutcomeUnknown(error: DesktopError): boolean {
  return error.code === OUTCOME_UNKNOWN;
}


export interface GraphNodeResponse { id: string; relative_path: string }
export interface GraphLinkResponse {
  source_note_id: string;
  target_reference: string;
  target_note_id: string | null;
  alias: string | null;
  line: number;
  unresolved_reason: "missing" | "ambiguous" | "invalid" | null;
}
export interface GraphResponse {
  vault_id: string;
  nodes: GraphNodeResponse[];
  links: GraphLinkResponse[];
}


export interface IndexResponse {
  vault_id: string; model: string; notes: number; chunks: number;
  generated: number; reused: number; removed: number;
}
export interface SearchHitResponse {
  chunk_id: string; note_id: string; relative_path: string; revision: string;
  ordinal: number; text: string; start_byte: number; end_byte: number;
  start_line: number; end_line: number; score: number;
}
export interface SearchResponse { vault_id: string; model: string; hits: SearchHitResponse[] }
export interface AskSource {
  number: number; note_id: string; relative_path: string;
  start_line: number; end_line: number; text: string; excerpt: boolean;
}
export interface AskUsage {
  context_tokens: number; budget: number; counter: string; input_tokens: number; output_tokens: number;
}
export interface AskResponse {
  vault_id: string; model: string; answer: string; answered_by_model: boolean; finish_reason: string;
  sources: AskSource[]; cited: number[]; usage: AskUsage;
}
