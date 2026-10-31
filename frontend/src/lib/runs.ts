import type { RunCard } from "../api/types";
import { plural } from "./format";

/** "owner/repo" for a GitHub URL, the archive or folder name otherwise. */
export function repoLabel(run: RunCard): string {
  const ref = run.source.ref.replace(/[\\/]+$/, "");
  if (run.source.kind === "git") {
    const m = ref.match(/^https?:\/\/[^/]+\/(.+?)(?:\.git)?$/);
    return m ? m[1] : ref;
  }
  return ref.split(/[\\/]/).pop() || ref;
}

export function commitLabel(run: RunCard): string {
  if (run.source.commit_sha) return run.source.commit_sha.slice(0, 7);
  return run.source.kind === "git" ? "HEAD" : run.source.kind === "zip" ? "upload" : "local";
}

export function runSubtitle(run: RunCard): string {
  const ref = run.source.git_ref || (run.source.kind === "git" ? "default branch" : run.source.kind);
  return `Run #${run.run_id} · ${ref}`;
}

/** The page a run opens on: where the user is needed or where its outcome is. */
export function runHref(run: RunCard): string {
  const page = run.status === "completed" ? "results" : run.status === "paused" ? "review" : "pipeline";
  return `/runs/${run.run_id}/${page}`;
}

export interface RunResult {
  text: string;
  /** 0..1 progress / share supported; null = no bar */
  bar: number | null;
}

export function runResult(run: RunCard): RunResult {
  switch (run.status) {
    case "completed": {
      const total = run.summary?.requirements ?? 0;
      const supported = run.summary?.status_counts?.supported ?? 0;
      return { text: `${supported} / ${total} supported`, bar: total ? supported / total : 0 };
    }
    case "paused":
      return {
        text: run.review.open ? `${plural(run.review.open, "item")} to review` : "Ready to continue",
        bar: null,
      };
    case "running": {
      const step = run.rail.find((s) => s.status === "running") ?? run.rail.find((s) => s.status === "waiting");
      const count = step?.total ? ` · ${step.done} / ${step.total}` : "";
      return { text: step ? `${step.label}${count}` : "Starting", bar: run.progress.fraction };
    }
    case "failed":
      return { text: firstSentence(run.error) || "Failed", bar: null };
    case "cancelled":
      return { text: "Cancelled", bar: null };
    default:
      return { text: "Queued", bar: null };
  }
}

function firstSentence(text: string | null): string {
  if (!text) return "";
  const s = text.split(/(?<=\.)\s/)[0];
  return s.length > 90 ? `${s.slice(0, 89)}…` : s;
}

/** Seconds from start to finish (or to now while it runs). */
export function runDuration(run: RunCard, now = Date.now()): number | null {
  if (!run.started_at) return null;
  const end = run.finished_at ? Date.parse(run.finished_at) : run.status === "running" ? now : Date.parse(run.started_at);
  return Math.max(0, (end - Date.parse(run.started_at)) / 1000);
}

export type RunFilter = "all" | "running" | "input" | "done" | "failed";

export const RUN_FILTERS: { id: RunFilter; label: string; statuses: string[] | null }[] = [
  { id: "all", label: "All", statuses: null },
  { id: "running", label: "Running", statuses: ["running", "queued"] },
  { id: "input", label: "Needs input", statuses: ["paused"] },
  { id: "done", label: "Completed", statuses: ["completed"] },
  { id: "failed", label: "Failed", statuses: ["failed", "cancelled"] },
];

export function filterRuns(runs: RunCard[], filter: RunFilter, query: string): RunCard[] {
  const statuses = RUN_FILTERS.find((f) => f.id === filter)?.statuses;
  const q = query.trim().toLowerCase();
  return runs.filter((r) => {
    if (statuses && !statuses.includes(r.status)) return false;
    if (!q) return true;
    const hay = [r.name, runSubtitle(r), r.srs_filename, repoLabel(r), r.source.commit_sha ?? "", r.source.ref]
      .join(" ")
      .toLowerCase();
    return hay.includes(q);
  });
}
