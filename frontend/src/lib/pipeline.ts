/**
 * What the Live pipeline page shows, derived from the run snapshot
 * (stages with status, done/total, timings and detail).  Pure functions.
 */

import type { RailStep, RunDetail, StageView } from "../api/types";
import { approx, clock, plural, shortComponent } from "./format";
import { stageMeta, type StageState } from "./status";

export const DOC_AGENTS = ["reader", "searcher", "writer", "verifier"] as const;

export function stageMap(run: RunDetail): Record<string, StageView> {
  return Object.fromEntries((run.stages ?? []).map((s) => [s.stage, s]));
}

/** One line under each step of the stage rail. */
export function railSub(step: RailStep, run: RunDetail): string {
  switch (step.status) {
    case "done":
      return step.group === "review"
        ? run.review.total ? `${run.review.resolved} resolved` : "Nothing to resolve"
        : step.elapsed_seconds != null ? `Done · ${clock(step.elapsed_seconds)}` : "Done";
    case "running":
      if (step.group === "ingest") {
        const lanes = (run.stages ?? []).filter((s) => s.lane && s.status === "running").map((s) => s.lane);
        return new Set(lanes).size > 1 ? "Running · 2 lanes" : "Running";
      }
      return step.total ? `${step.done} / ${step.total}` : "Running";
    case "waiting":
      return "Waiting for you";
    case "failed":
      return "Failed";
    case "cancelled":
      return "Cancelled";
    default:
      return "Queued";
  }
}

/** Elapsed run time; while paused it stops when ingestion finished. */
export function runElapsed(run: RunDetail, now = Date.now()): number | null {
  if (!run.started_at) return null;
  const start = Date.parse(run.started_at);
  let end = now;
  if (run.finished_at) end = Date.parse(run.finished_at);
  else if (run.status !== "running") {
    const finished = (run.stages ?? []).map((s) => s.finished_at).filter(Boolean).map((t) => Date.parse(t!));
    end = finished.length ? Math.max(...finished) : start;
  }
  return Math.max(0, (end - start) / 1000);
}

export function overallLabel(run: RunDetail): string {
  const s = stageMap(run);
  if (run.status === "completed") return "Run complete";
  if (run.status === "paused") return "Waiting for your review";
  if (run.status === "cancelled") return "Cancelled";
  if (run.status === "failed") {
    const failed = (run.stages ?? []).find((x) => x.status === "failed");
    return failed ? `Stopped during ${failed.label.toLowerCase()}` : "Could not start";
  }
  if (s.verify?.status === "running") return "Verifying requirements";
  if (s.map?.status === "running") return "Mapping requirements to code";
  if (s.search?.status === "running" || s.index_srs?.status === "running") return "Searching for candidate code";
  const a = ["fetch", "docstrings", "index_code"].some((k) => s[k]?.status === "running");
  const b = ["extract", "prepare_review"].some((k) => s[k]?.status === "running");
  if (a && b) return "Ingesting code and SRS in parallel";
  if (a) return "Ingesting code";
  if (b) return "Extracting requirements";
  return "Starting";
}

export function overallColor(status: RunDetail["status"]): string {
  return { paused: "var(--rev)", failed: "var(--bad)", cancelled: "var(--nf)", completed: "var(--ok)" }[status as string]
    ?? "var(--accent)";
}

export function ingestDone(run: RunDetail): boolean {
  return run.rail.find((r) => r.group === "ingest")?.status === "done";
}

export function traceStarted(run: RunDetail): boolean {
  const s = stageMap(run);
  return ["index_srs", "search", "map", "verify", "results"].some((k) => s[k] && s[k].status !== "queued");
}

// ---------------------------------------------------------------------------
// Lanes
// ---------------------------------------------------------------------------

export interface StepRow {
  key: string;
  label: string;
  state: StageState;
  detail?: string;
  time?: string;
  /** DocAgent sub-agents for the docstring step */
  agents?: { label: string; state: "done" | "current" | "todo" }[];
  target?: string;
}

export interface LaneView {
  lane: "A" | "B";
  title: string;
  elapsed: number | null;
  eta: number | null;
  counter: string;
  fraction: number;
  state: StageState;
  steps: StepRow[];
}

function laneState(stages: StageView[]): StageState {
  const st = stages.map((s) => s.status);
  if (st.includes("failed")) return "failed";
  if (st.includes("cancelled")) return "cancelled";
  if (st.every((x) => x === "done" || x === "skipped")) return "done";
  if (st.includes("running") || st.includes("done")) return "running";
  return "queued";
}

function laneElapsed(stages: StageView[], now: number): number | null {
  const starts = stages.map((s) => s.started_at).filter(Boolean).map((t) => Date.parse(t!));
  if (!starts.length) return null;
  const running = stages.some((s) => s.status === "running");
  const ends = stages.map((s) => s.finished_at).filter(Boolean).map((t) => Date.parse(t!));
  const end = running || !ends.length ? now : Math.max(...ends);
  return Math.max(0, (end - Math.min(...starts)) / 1000);
}

function time(s: StageView): string {
  if (s.status === "running" && s.total) return `${s.done} / ${s.total}`;
  if (s.status === "done" && s.elapsed_seconds != null) return clock(s.elapsed_seconds);
  return "";
}

export function codeLane(run: RunDetail, repo: string, now = Date.now()): LaneView {
  const s = stageMap(run);
  const fetch = s.fetch, doc = s.docstrings, index = s.index_code;
  const src = fetch?.detail?.source;
  const steps: StepRow[] = [
    {
      key: "fetch", label: "Fetch source", state: fetch?.status ?? "queued", time: fetch ? time(fetch) : "",
      detail: src ? `${src.name}${src.commit_sha ? ` @ ${String(src.commit_sha).slice(0, 7)}` : ""} · ${plural(src.stats?.python_files ?? 0, "Python file")}` : undefined,
    },
    {
      key: "docstrings", label: "Parse components and generate docstrings", state: doc?.status ?? "queued",
      time: doc ? time(doc) : "",
      detail: doc?.status === "done" ? `${doc.total ?? doc.done} components` : doc?.total ? `${doc.total} components in dependency order` : undefined,
    },
    {
      key: "index_code", label: "Index for search", state: index?.status ?? "queued", time: index ? time(index) : "",
      detail: index?.detail?.report
        ? `${index.detail.report.components} components · ${index.detail.report.relationships ?? 0} relationships · embeddings + keyword index`
        : "Embeddings + keyword index",
    },
  ];
  if (doc?.status === "running" && doc.detail?.current) {
    const current = DOC_AGENTS.indexOf(doc.detail.agent);
    steps[1].target = shortComponent(doc.detail.current);
    steps[1].agents = DOC_AGENTS.map((a, i) => ({
      label: a[0].toUpperCase() + a.slice(1),
      state: current < 0 ? (i === 0 ? "current" : "todo") : i < current ? "done" : i === current ? "current" : "todo",
    }));
  }
  const total = doc?.total ?? null;
  const fraction = laneFraction([fetch, doc, index], [1, 40, 2]);
  return {
    lane: "A", title: `Code · ${repo}`, steps, fraction,
    elapsed: laneElapsed([fetch, doc, index].filter(Boolean) as StageView[], now),
    eta: doc?.status === "running" ? doc.eta_seconds : null,
    state: laneState([fetch, doc, index].filter(Boolean) as StageView[]),
    counter: doc?.status === "failed" ? "Docstring generation failed"
      : fetch?.status === "failed" ? "Fetching the code failed"
        : total != null ? `Docstrings ${doc!.done} / ${total} components`
          : fetch?.status === "running" ? "Fetching the code" : "Waiting to start",
  };
}

export function srsLane(run: RunDetail, srsName: string, now = Date.now()): LaneView {
  const s = stageMap(run);
  const ex = s.extract, prep = s.prepare_review;
  const d = ex?.detail ?? {};
  const phase: string | undefined = d.phase;
  // The SRS Agent's phases inside the extract stage: earlier phases are done,
  // the current one carries the stage's state, later ones are queued.
  const order = ["detect", "judge", "extract"];
  const at = ex?.status === "done" || phase === "done" ? order.length : Math.max(0, order.indexOf(phase ?? "detect"));
  const sub = (p: string): StageState => {
    const i = order.indexOf(p);
    if (!ex || ex.status === "queued") return "queued";
    if (i < at) return "done";
    if (i > at) return "queued";
    return ex.status === "done" ? "done" : ex.status;
  };
  const judge = d.judge;
  const steps: StepRow[] = [
    {
      key: "detect", label: "Parse document and detect candidate requirements", state: sub("detect"),
      detail: d.candidates != null ? `${plural(d.candidates, "candidate")}${d.segmentation?.labelled != null ? ` · ${d.segmentation.labelled} with an ID` : ""}` : undefined,
    },
    {
      key: "judge", label: "AI judge reviews ambiguous candidates", state: sub("judge"),
      time: judge && sub("judge") === "running" ? `${judge.batch} / ${judge.batches}` : "",
      detail: judge ? plural(judge.batches, "batch", "batches") : sub("judge") === "done" ? "No ambiguous candidates" : undefined,
    },
    {
      key: "extract", label: "Extract structured requirements", state: sub("extract"),
      time: phase === "extract" && ex?.total ? `${ex.done} / ${ex.total}` : ex?.status === "done" && ex.elapsed_seconds != null ? clock(ex.elapsed_seconds) : "",
      detail: phase === "extract" || ex?.status === "done" ? "ID, title, type, normalized text, conditions" : undefined,
    },
    {
      key: "prepare_review", label: "Prepare review", state: prep?.status ?? "queued", time: prep ? time(prep) : "",
      detail: prep?.status === "done" ? `${plural(prep.detail?.counts?.open ?? 0, "item")} need review` : "Uncertain, incomplete and duplicate items",
    },
  ];
  const counter = ex?.status === "done" ? `Requirements ${ex.done} / ${ex.total ?? ex.done} extracted`
    : phase === "extract" && ex?.total ? `Requirements ${ex.done} / ${ex.total} extracted`
      : judge ? `Judge batch ${judge.batch} / ${judge.batches}`
        : ex?.status === "running" ? "Reading the document" : "Waiting to start";
  return {
    lane: "B", title: `SRS · ${srsName}`, steps, counter,
    fraction: laneFraction([ex, prep], [15, 1]),
    elapsed: laneElapsed([ex, prep].filter(Boolean) as StageView[], now),
    eta: ex?.status === "running" ? ex.eta_seconds : null,
    state: laneState([ex, prep].filter(Boolean) as StageView[]),
  };
}

function laneFraction(stages: (StageView | undefined)[], weights: number[]): number {
  let total = 0, done = 0;
  stages.forEach((s, i) => {
    total += weights[i];
    if (!s) return;
    const f = s.status === "done" || s.status === "skipped" ? 1 : s.status === "running" ? s.fraction ?? 0.02 : 0;
    done += weights[i] * f;
  });
  return total ? done / total : 0;
}

// ---------------------------------------------------------------------------
// Tracing agents
// ---------------------------------------------------------------------------

export interface AgentCard {
  name: string;
  state: StageState;
  counter: string;
  time: string;
  fraction: number;
  note: string;
}

export function agentCards(run: RunDetail, verifierModel: string | undefined): AgentCard[] {
  const s = stageMap(run);
  const timeOf = (st?: StageView) =>
    !st || st.elapsed_seconds == null ? "" :
      st.status === "running" && st.eta_seconds != null ? `${clock(st.elapsed_seconds)} · ETA ${approx(st.eta_seconds)}` : clock(st.elapsed_seconds);
  const frac = (st?: StageView) => (!st ? 0 : st.status === "done" ? 1 : st.fraction ?? 0);
  const count = (st?: StageView) => (st?.total ? `${st.done} / ${st.total}` : "—");
  const search = s.search, map = s.map, verify = s.verify;
  const without: string[] = search?.detail?.without_candidates ?? [];
  const links = map?.detail?.links;
  return [
    {
      name: "Search agent", state: search?.status ?? "queued", counter: count(search), time: timeOf(search), fraction: frac(search),
      note: search?.status === "done"
        ? `${(search.total ?? 0) - without.length} with candidates${without.length ? ` · ${without.length} with none (${without.slice(0, 3).join(", ")}${without.length > 3 ? "…" : ""})` : ""}`
        : "Keyword + semantic search over code and docstrings",
    },
    {
      name: "Mapping agent", state: map?.status ?? "queued", counter: count(map), time: timeOf(map), fraction: frac(map),
      note: links ? `${links.direct} direct links · ${links.supporting} supporting links` : "Direct code plus supporting subgraph",
    },
    {
      name: "Verifier agent", state: verify?.status ?? "queued",
      counter: verify?.status === "running" && verify.detail?.current ? `${verify.detail.current} (${verify.done + 1} / ${verify.total ?? "?"})` : count(verify),
      time: timeOf(verify), fraction: frac(verify),
      note: verify?.status === "failed" ? verify.error ?? "Failed" : `~20 s per requirement${verifierModel ? ` on ${verifierModel}` : ""}`,
    },
  ];
}

export { stageMeta };
