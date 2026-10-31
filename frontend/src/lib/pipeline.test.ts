import { describe, expect, it } from "vitest";

import type { RunDetail, StageView } from "../api/types";
import { makeRun } from "../test/fixtures";
import { agentCards, codeLane, overallLabel, railSub, runElapsed, srsLane, traceStarted } from "./pipeline";

const T0 = "2026-10-31T10:00:00Z";
const at = (s: number) => new Date(Date.parse(T0) + s * 1000).toISOString();

function stage(stage: string, lane: "A" | "B" | null, status: StageView["status"], extra: Partial<StageView> = {}): StageView {
  return { stage, label: stage, lane, group: "ingest", unit: "", status, done: 0, total: null, fraction: null,
    elapsed_seconds: null, eta_seconds: null, started_at: null, finished_at: null, error: null, detail: {}, ...extra };
}

function detail(stages: StageView[], extra: Partial<RunDetail> = {}): RunDetail {
  return { ...makeRun(4, "running", { started_at: T0 }), stages, active: true, ...extra } as RunDetail;
}

describe("pipeline view", () => {
  it("rail sub-lines", () => {
    const run = detail([stage("docstrings", "A", "running"), stage("extract", "B", "running")],
      { review: { total: 7, resolved: 7, open: 0, open_by_category: {} } });
    expect(railSub({ group: "ingest", label: "Ingest", status: "running", done: 0, total: null, elapsed_seconds: 5 }, run)).toBe("Running · 2 lanes");
    expect(railSub({ group: "verify", label: "Verify", status: "running", done: 17, total: 39, elapsed_seconds: 5 }, run)).toBe("17 / 39");
    expect(railSub({ group: "review", label: "Review", status: "done", done: 7, total: 7, elapsed_seconds: 5 }, run)).toBe("7 resolved");
    expect(railSub({ group: "map", label: "Map", status: "done", done: 39, total: 39, elapsed_seconds: 111 }, run)).toBe("Done · 01:51");
    expect(railSub({ group: "review", label: "Review", status: "waiting", done: 0, total: 7, elapsed_seconds: null }, run)).toBe("Waiting for you");
  });

  it("elapsed stops while paused", () => {
    const run = detail([stage("extract", "B", "done", { finished_at: at(300) })], { status: "paused" });
    expect(runElapsed(run, Date.parse(at(9999)))).toBe(300);
    const live = detail([], { status: "running" });
    expect(runElapsed(live, Date.parse(at(42)))).toBe(42);
  });

  it("overall label follows the busiest stage", () => {
    expect(overallLabel(detail([stage("docstrings", "A", "running"), stage("extract", "B", "running")]))).toBe("Ingesting code and SRS in parallel");
    expect(overallLabel(detail([stage("verify", null, "running")]))).toBe("Verifying requirements");
    expect(overallLabel(detail([stage("docstrings", "A", "failed")], { status: "failed" }))).toBe("Stopped during docstrings");
    expect(overallLabel(detail([], { status: "paused" }))).toBe("Waiting for your review");
  });

  it("code lane shows DocAgent's sub-agents for the current component", () => {
    const run = detail([
      stage("fetch", "A", "done", { detail: { source: { name: "library", commit_sha: "4f2a9c1abc", stats: { python_files: 9 } } } }),
      stage("docstrings", "A", "running", { done: 21, total: 41, fraction: 21 / 41, eta_seconds: 800,
        detail: { current: "library_system.models.book.Book.checkout_copy", agent: "writer" } }),
      stage("index_code", "A", "queued"),
    ]);
    const lane = codeLane(run, "library", Date.parse(at(60)));
    expect(lane.counter).toBe("Docstrings 21 / 41 components");
    expect(lane.eta).toBe(800);
    expect(lane.steps[0].detail).toBe("library @ 4f2a9c1 · 9 Python files");
    expect(lane.steps[1].target).toBe("Book.checkout_copy");
    expect(lane.steps[1].agents!.map((a) => a.state)).toEqual(["done", "done", "current", "todo"]);
    expect(lane.state).toBe("running");
    const failed = codeLane(detail([stage("fetch", "A", "done"), stage("docstrings", "A", "failed"), stage("index_code", "A", "queued")]), "x");
    expect(failed.counter).toBe("Docstring generation failed");
    expect(failed.state).toBe("failed");
  });

  it("SRS lane maps the agent's phases to steps", () => {
    const running = srsLane(detail([
      stage("extract", "B", "running", { done: 17, total: 39, detail: { phase: "extract", candidates: 40, segmentation: { labelled: 39 }, judge: { batch: 1, batches: 1, done: true } } }),
      stage("prepare_review", "B", "queued"),
    ]), "SRS.docx");
    expect(running.steps.map((s) => s.state)).toEqual(["done", "done", "running", "queued"]);
    expect(running.steps[0].detail).toBe("40 candidates · 39 with an ID");
    expect(running.steps[2].time).toBe("17 / 39");
    expect(running.counter).toBe("Requirements 17 / 39 extracted");
    const judging = srsLane(detail([stage("extract", "B", "running", { detail: { phase: "judge", judge: { batch: 2, batches: 3 } } }), stage("prepare_review", "B", "queued")]), "s");
    expect(judging.steps.map((s) => s.state)).toEqual(["done", "running", "queued", "queued"]);
    expect(judging.counter).toBe("Judge batch 2 / 3");
    const noJudge = srsLane(detail([stage("extract", "B", "done", { done: 39, total: 39 }), stage("prepare_review", "B", "done", { detail: { counts: { open: 0 } } })]), "s");
    expect(noJudge.steps[1].detail).toBe("No ambiguous candidates");
    expect(noJudge.state).toBe("done");
  });

  it("agent cards", () => {
    const run = detail([
      stage("search", null, "done", { done: 39, total: 39, detail: { without_candidates: ["FR-028"] } }),
      stage("map", null, "done", { done: 39, total: 39, detail: { links: { direct: 56, supporting: 91 } } }),
      stage("verify", null, "running", { done: 16, total: 39, fraction: 16 / 39, elapsed_seconds: 320, eta_seconds: 460, detail: { current: "FR-017" } }),
    ]);
    const [search, map, verify] = agentCards(run, "qwen2.5-coder:7b");
    expect(search.note).toBe("38 with candidates · 1 with none (FR-028)");
    expect(map.note).toBe("56 direct links · 91 supporting links");
    expect(verify.counter).toBe("FR-017 (17 / 39)");
    expect(verify.time).toBe("05:20 · ETA ~8 min");
    expect(verify.note).toContain("qwen2.5-coder:7b");
    expect(traceStarted(run)).toBe(true);
    expect(traceStarted(detail([stage("search", null, "queued")]))).toBe(false);
  });
});
