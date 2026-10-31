/** Shapes returned by the Tracelight API (backend/tracelight/api). */

import type { RunStatus, StageState } from "../lib/status";

export interface RunEvent {
  event_id: number;
  run_id: number;
  ts: string;
  stage: string | null;
  lane: "A" | "B" | null;
  level: "info" | "ok" | "warn" | "error";
  message: string;
  data: Record<string, unknown>;
}

export interface StageView {
  stage: string;
  label: string;
  lane: "A" | "B" | null;
  group: string;
  unit: string;
  status: StageState;
  done: number;
  total: number | null;
  fraction: number | null;
  elapsed_seconds: number | null;
  eta_seconds: number | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  detail: Record<string, any>;
}

export interface RailStep {
  group: string;
  label: string;
  status: StageState;
  done: number;
  total: number | null;
  elapsed_seconds: number | null;
}

export interface ReviewCounts {
  total: number;
  resolved: number;
  open: number;
  open_by_category: Record<string, number>;
}

export interface RunSummary {
  requirements?: number;
  status_counts?: Record<string, number>;
  unreviewed?: string[];
  components?: number;
  links?: { direct: number; supporting: number; docstrings: number };
  verifier_model?: string;
}

export interface RunCard {
  run_id: number;
  name: string;
  status: RunStatus;
  error: string | null;
  source: { kind: "zip" | "folder" | "git"; ref: string; git_ref: string | null; commit_sha: string | null };
  srs_filename: string;
  document_id: string | null;
  repo_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  summary: RunSummary;
  models: Record<string, string> | null;
  progress: { fraction: number; remaining_seconds: number | null };
  rail: RailStep[];
  review: ReviewCounts;
}

export interface Lane {
  lane: "A" | "B";
  title: string;
  stages: StageView[];
  log: RunEvent[];
}

export interface RunDetail extends RunCard {
  stages: StageView[];
  active: boolean;
  lanes?: Lane[];
  log?: RunEvent[];
}

export interface Health {
  agents: Record<string, { dir: string; python: string; dir_ok: boolean; python_ok: boolean }>;
  ollama_host: string;
  database: { ok: boolean; error?: string };
  ollama: { ok: boolean; models?: string[]; error?: string };
  models: Record<string, { name: string; pulled: boolean | null }>;
}

export interface SourceStats {
  files: number;
  python_files: number;
  python_lines: number;
  bytes: number;
  classes: number;
  functions: number;
  methods: number;
  components: number;
  unparsable: string[];
}

export interface SourceWarning {
  code: string;
  level: "warn" | "error";
  message: string;
  files?: string[];
}

export interface InspectResult {
  kind: "zip" | "folder" | "git";
  url?: string;
  stats: SourceStats | null;
  warnings: SourceWarning[];
  note?: string;
}

export interface AppSettings {
  models: Record<"docagent" | "srs" | "judge" | "verifier", string>;
  ollama_host: string;
  ingest: { parallel: boolean; overwrite_docstrings: boolean };
  search: { top_n: number; candidate_k: number };
  mapping: { max_direct_rank: number; max_supporting: number; use_source_references: boolean };
  verification: { claims: string };
  review: { duplicate_threshold: number };
  limits: { max_upload_mb: number; large_repo_files: number; large_repo_components: number };
  source: { exclude_dirs: string[] };
}

export interface VerdictView {
  status: string;
  source: "human" | "verifier" | null;
  machine: string | null;
  note?: string | null;
}

export interface Flag {
  code: string;
  label: string;
  level: "info" | "warn" | "error";
}

export interface ResultRow {
  requirement_id: string;
  title: string;
  type: string;
  subtype: string;
  verdict: VerdictView;
  claims: { supported: number; total: number };
  links: { direct: number; supporting: number; total: number };
  flags: Flag[];
  human: string | null;
  location: Record<string, unknown>;
  verified_at: string | null;
}

export interface ResultsSummary {
  requirements: number;
  counts: Record<string, number>;
  pending: number;
  supported: number;
  likely_not_implemented: number;
  needs_attention: number;
  overridden: number;
  unreviewed: number;
  components: { total: number; cited_as_evidence: number };
}

export interface Results {
  ready: boolean;
  summary: ResultsSummary | null;
  requirements: ResultRow[];
}

export type ReviewCategory = "uncertain" | "flagged" | "incomplete" | "split";
export type Resolution = "kept" | "edited" | "discarded" | "merged" | "unreviewed";

export interface ReviewItem {
  run_id: number;
  item_key: string;
  position: number;
  category: ReviewCategory;
  requirement_id: string | null;
  payload: {
    kind: "requirement" | "candidate" | "failure" | "skipped_section" | "skipped_table";
    title: string;
    type?: string | null;
    subtype?: string | null;
    confidence?: string | null;
    source_text: string;
    normalized_text: string;
    location: Record<string, number | string>;
    reasons: string[];
    suggestion?: { action: "edit" | "merge" | "discard"; target?: string };
    items?: string[];
    index?: number;
    also?: string[];
    similarity?: number;
  };
  resolution: Resolution | null;
  resolution_data: { into?: string; text?: string; requirement_id?: string; auto?: boolean };
  resolved_at: string | null;
}

export interface ReviewState {
  ready: boolean;
  status: string;
  counts: ReviewCounts;
  items: ReviewItem[];
  requirements: { index: number; requirement_id: string; title: string; type: string; subtype: string; location: Record<string, number | string> }[];
}

export interface DocBlock {
  kind: "heading" | "paragraph" | "list_item" | "table";
  text: string;
  level: number;
  rows: string[][];
  location: Record<string, number | string>;
}

export interface MergeTarget {
  requirement_id: string;
  title: string;
  similarity: number;
  suggested: boolean;
}
