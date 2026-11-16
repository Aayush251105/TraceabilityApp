/**
 * Verdicts and run/stage states: label + colour + glyph shape, exactly as in
 * the design system.  Status is never colour alone (shape and label too).
 */

export type Verdict =
  | "supported"
  | "partially_supported"
  | "not_supported_by_candidate"
  | "not_found"
  | "insufficient_evidence"
  | "needs_review";

export interface StatusMeta {
  label: string;
  /** foreground / border colour */
  c: string;
  /** chip background */
  b: string;
  /** glyph fill (a gradient for "half" states) */
  ib: string;
  /** character drawn inside the glyph */
  g: string;
  /** glyph radius: circles for outcomes, squares for states that need attention */
  r: string;
}

const half = (c: string) => `linear-gradient(90deg,${c} 50%,transparent 50%)`;

export const VERDICTS: Record<Verdict, StatusMeta> = {
  supported: { label: "Supported", c: "var(--ok)", b: "var(--ok-bg)", ib: "var(--ok)", g: "✓", r: "50%" },
  partially_supported: { label: "Partially supported", c: "var(--part)", b: "var(--part-bg)", ib: half("var(--part)"), g: "", r: "50%" },
  not_supported_by_candidate: { label: "Not supported by candidate", c: "var(--bad)", b: "var(--bad-bg)", ib: "var(--bad)", g: "✕", r: "50%" },
  not_found: { label: "Not found", c: "var(--nf)", b: "var(--nf-bg)", ib: "transparent", g: "", r: "50%" },
  insufficient_evidence: { label: "Insufficient evidence", c: "var(--ins)", b: "var(--ins-bg)", ib: "var(--ins)", g: "?", r: "50%" },
  needs_review: { label: "Needs review", c: "var(--rev)", b: "var(--rev-bg)", ib: "var(--rev)", g: "!", r: "50%" },
};

export const VERDICT_ORDER: Verdict[] = [
  "supported",
  "partially_supported",
  "not_supported_by_candidate",
  "not_found",
  "insufficient_evidence",
  "needs_review",
];

export const PENDING: StatusMeta = { label: "Pending", c: "var(--fg3)", b: "var(--nf-bg)", ib: "transparent", g: "", r: "50%" };

export function verdictMeta(v: string | null | undefined): StatusMeta {
  return (v && VERDICTS[v as Verdict]) || PENDING;
}

/** Run and stage states (stage rail, lanes, run list). */
export type StageState = "queued" | "running" | "done" | "waiting" | "failed" | "cancelled" | "skipped";

export const STAGE_STATES: Record<StageState, StatusMeta> = {
  queued: { label: "Queued", c: "var(--fg3)", b: "var(--nf-bg)", ib: "transparent", g: "", r: "50%" },
  running: { label: "Running", c: "var(--accent)", b: "var(--accent-bg)", ib: half("var(--accent)"), g: "", r: "50%" },
  done: { label: "Done", c: "var(--ok)", b: "var(--ok-bg)", ib: "var(--ok)", g: "✓", r: "50%" },
  waiting: { label: "Waiting for you", c: "var(--rev)", b: "var(--rev-bg)", ib: "var(--rev)", g: "!", r: "2px" },
  failed: { label: "Failed", c: "var(--bad)", b: "var(--bad-bg)", ib: "var(--bad)", g: "✕", r: "2px" },
  cancelled: { label: "Cancelled", c: "var(--nf)", b: "var(--nf-bg)", ib: "var(--nf)", g: "–", r: "2px" },
  skipped: { label: "Skipped", c: "var(--fg3)", b: "var(--nf-bg)", ib: "transparent", g: "", r: "50%" },
};

/** Run statuses as stored by the backend → the state shown. */
export type RunStatus = "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";

export const RUN_STATES: Record<RunStatus, StatusMeta> = {
  queued: STAGE_STATES.queued,
  running: STAGE_STATES.running,
  paused: { ...STAGE_STATES.waiting, label: "Paused for review" },
  completed: { ...STAGE_STATES.done, label: "Completed" },
  failed: STAGE_STATES.failed,
  cancelled: STAGE_STATES.cancelled,
};

export function stageMeta(s: string | null | undefined): StatusMeta {
  return STAGE_STATES[(s as StageState) ?? "queued"] ?? STAGE_STATES.queued;
}

export function runMeta(s: string | null | undefined): StatusMeta {
  return RUN_STATES[(s as RunStatus) ?? "queued"] ?? RUN_STATES.queued;
}
