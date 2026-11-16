import { describe, expect, it } from "vitest";

import { makeRun } from "../test/fixtures";
import { commitLabel, filterRuns, repoLabel, runDuration, runHref, runResult, runSubtitle } from "./runs";

describe("run rows", () => {
  it("repository labels per source kind", () => {
    expect(repoLabel(makeRun(1, "running", { source: { kind: "git", ref: "https://github.com/acme/library_system.git", git_ref: "main", commit_sha: "4f2a9c1abcdef" } }))).toBe("acme/library_system");
    expect(repoLabel(makeRun(1, "running", { source: { kind: "zip", ref: "C:\\data\\runs\\run-3\\input\\payroll-core.zip", git_ref: null, commit_sha: null } }))).toBe("payroll-core.zip");
    expect(repoLabel(makeRun(1, "running"))).toBe("library_system");
  });

  it("commit and subtitle", () => {
    const git = makeRun(14, "running", { source: { kind: "git", ref: "https://github.com/a/b", git_ref: "main", commit_sha: "4f2a9c1abcdef" } });
    expect(commitLabel(git)).toBe("4f2a9c1");
    expect(runSubtitle(git)).toBe("Run #14 · main");
    expect(commitLabel(makeRun(2, "completed"))).toBe("local");
  });

  it("results per status", () => {
    const done = makeRun(12, "completed", { summary: { requirements: 39, status_counts: { supported: 31 } } });
    expect(runResult(done)).toEqual({ text: "31 / 39 supported", bar: 31 / 39 });
    expect(runResult(makeRun(13, "paused", { review: { total: 9, resolved: 2, open: 7, open_by_category: {} } })).text).toBe("7 items to review");
    expect(runResult(makeRun(13, "paused")).text).toBe("Ready to continue");
    const running = makeRun(14, "running", {
      progress: { fraction: 0.44, remaining_seconds: 300 },
      rail: [{ group: "verify", label: "Verify", status: "running", done: 17, total: 39, elapsed_seconds: 10 }],
    });
    expect(runResult(running)).toEqual({ text: "Verify · 17 / 39", bar: 0.44 });
    expect(runResult(makeRun(11, "failed", { error: "Verifier agent: the model failed 3 times. Check Ollama, then resume." })).text)
      .toBe("Verifier agent: the model failed 3 times.");
  });

  it("links open where the user is needed", () => {
    expect(runHref(makeRun(1, "completed"))).toBe("/runs/1/results");
    expect(runHref(makeRun(2, "paused"))).toBe("/runs/2/review");
    expect(runHref(makeRun(3, "failed"))).toBe("/runs/3/pipeline");
  });

  it("duration", () => {
    const r = makeRun(1, "completed", { started_at: "2026-10-31T09:00:00Z", finished_at: "2026-10-31T09:34:08Z" });
    expect(runDuration(r)).toBe(34 * 60 + 8);
    const live = makeRun(2, "running", { started_at: "2026-10-31T09:00:00Z" });
    expect(runDuration(live, Date.parse("2026-10-31T09:01:00Z"))).toBe(60);
    expect(runDuration(makeRun(3, "queued", { started_at: null }))).toBeNull();
  });

  it("filters and search", () => {
    const runs = [makeRun(1, "running"), makeRun(2, "paused"), makeRun(3, "completed"), makeRun(4, "cancelled"),
      makeRun(5, "failed", { srs_filename: "inventory_srs.docx" })];
    expect(filterRuns(runs, "failed", "").map((r) => r.run_id)).toEqual([4, 5]);
    expect(filterRuns(runs, "input", "").map((r) => r.run_id)).toEqual([2]);
    expect(filterRuns(runs, "all", "inventory").map((r) => r.run_id)).toEqual([5]);
    expect(filterRuns(runs, "all", "run #3").map((r) => r.run_id)).toEqual([3]);
  });
});
