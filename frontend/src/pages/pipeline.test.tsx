import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RunDetail, StageView } from "../api/types";
import { makeRun, mockFetch } from "../test/fixtures";
import { Pipeline } from "./Pipeline";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static CLOSED = 2;
  readyState = 1;
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  listeners: Record<string, ((e: MessageEvent) => void)[]> = {};
  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(fn);
  }
  emit(type: string, data: unknown) {
    for (const fn of this.listeners[type] ?? []) fn(new MessageEvent(type, { data: JSON.stringify(data) }));
  }
  close() {
    this.readyState = 2;
  }
}

function stage(key: string, lane: "A" | "B" | null, group: string, status: StageView["status"], extra: Partial<StageView> = {}): StageView {
  return { stage: key, label: key, lane, group, unit: "", status, done: 0, total: null, fraction: null, elapsed_seconds: null,
    eta_seconds: null, started_at: null, finished_at: null, error: null, detail: {}, ...extra };
}

const RAIL = (status: Record<string, StageView["status"]>) =>
  ["ingest", "review", "search", "map", "verify", "results"].map((g) => ({
    group: g, label: g[0].toUpperCase() + g.slice(1), status: status[g] ?? "queued", done: 0, total: null, elapsed_seconds: null,
  }));

function run(extra: Partial<RunDetail>): RunDetail {
  return {
    ...makeRun(4, "running", { started_at: "2026-10-31T10:00:00Z" }),
    active: true,
    lanes: [],
    stages: [
      stage("fetch", "A", "ingest", "done"), stage("docstrings", "A", "ingest", "done", { done: 41, total: 41 }),
      stage("index_code", "A", "ingest", "done", { detail: { report: { components: 41, relationships: 58, docstrings: { generated: 36 } } } }),
      stage("extract", "B", "ingest", "done", { done: 39, total: 39, detail: { candidates: 40 } }),
      stage("prepare_review", "B", "ingest", "done", { detail: { counts: { open: 3 }, requirements: 39 } }),
      stage("review", null, "review", "waiting"),
    ],
    ...extra,
  } as RunDetail;
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/runs/4/pipeline"]}>
        <Routes>
          <Route path="/runs/:runId/pipeline" element={<Pipeline />} />
          <Route path="/runs/:runId/review" element={<div>review page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});
afterEach(() => vi.unstubAllGlobals());

describe("Live pipeline page", () => {
  it("paused for review: banner, lane summaries, queued agents, link to review", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "GET /api/runs/4": run({ status: "paused", rail: RAIL({ ingest: "done", review: "waiting" }),
        review: { total: 10, resolved: 7, open: 3, open_by_category: {} } }),
    }).fn);
    renderPage();
    expect(await screen.findByText("Your input is needed: 3 items to review")).toBeInTheDocument();
    expect(screen.getByText("Paused for review")).toBeInTheDocument();
    expect(screen.getByText(/41 components · 58 relationships · 36 docstrings written/)).toBeInTheDocument();
    expect(screen.getByText("Queued after review")).toBeInTheDocument();
    expect(FakeEventSource.instances[0].url).toBe("/api/runs/4/stream");
    fireEvent.click(screen.getByText("Review requirements →"));
    expect(await screen.findByText("review page")).toBeInTheDocument();
  });

  it("streams log lines into the right lane", async () => {
    const r = run({ status: "running", rail: RAIL({ ingest: "running" }) });
    r.stages = r.stages!.map((s) => (s.stage === "extract" ? { ...s, status: "running", done: 3, total: 39, detail: { phase: "extract" } } : s));
    vi.stubGlobal("fetch", mockFetch({ "GET /api/runs/4": r }).fn);
    renderPage();
    await screen.findByText("Requirements 3 / 39 extracted");
    FakeEventSource.instances[0].emit("log", { event_id: 9, run_id: 4, ts: "2026-10-31T10:01:00Z", stage: "extract",
      lane: "B", level: "info", message: "Extracted FR-004 “Remove a book”", data: {} });
    expect(await screen.findByText("Extracted FR-004 “Remove a book”")).toBeInTheDocument();
    FakeEventSource.instances[0].emit("run", { ...r, progress: { fraction: 0.4, remaining_seconds: 420 } });
    expect(await screen.findByText("~7 min")).toBeInTheDocument();
  });

  it("cancel asks first, then cancels", async () => {
    const api = mockFetch({
      "GET /api/runs/4": run({ status: "running", rail: RAIL({ ingest: "running" }) }),
      "POST /api/runs/4/cancel": { run_id: 4, cancelling: true },
    });
    vi.stubGlobal("fetch", api.fn);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    expect(screen.getByRole("dialog", { name: "Cancel Run #4?" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Keep running" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "POST")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Cancel run" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Cancel run" }).at(-1)!);
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.url === "/api/runs/4/cancel")).toBe(true));
  });

  it("a failed run explains why and can be resumed", async () => {
    const r = run({ status: "failed", error: "Verifier agent: the model failed 3 times in a row.", rail: RAIL({ ingest: "done", review: "done", search: "done", map: "done", verify: "failed" }) });
    r.stages = [...r.stages!.map((s) => (s.stage === "review" ? { ...s, status: "done" as const } : s)),
      stage("search", null, "search", "done", { done: 39, total: 39 }), stage("map", null, "map", "done", { done: 39, total: 39 }),
      stage("verify", null, "verify", "failed", { done: 22, total: 39, label: "Verifier agent", error: "model failed" })];
    const api = mockFetch({ "GET /api/runs/4": r, "GET /api/runs/4/results": { ready: true, summary: null, requirements: [] },
      "POST /api/runs/4/resume": { run_id: 4, started: true } });
    vi.stubGlobal("fetch", api.fn);
    renderPage();
    expect(await screen.findByText("Verifier agent stopped")).toBeInTheDocument();
    expect(screen.getByText(/the model failed 3 times in a row/)).toBeInTheDocument();
    expect(screen.getByText("17")).toBeInTheDocument();                       // not verified yet
    fireEvent.click(screen.getByRole("button", { name: "Resume run" }));
    await waitFor(() => expect(api.calls.some((c) => c.url === "/api/runs/4/resume")).toBe(true));
  });

  it("unknown run", async () => {
    vi.stubGlobal("fetch", mockFetch({}).fn);
    renderPage();
    expect(await screen.findByText("Run not found.")).toBeInTheDocument();
  });
});
