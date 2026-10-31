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
