import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ResultRow } from "../api/types";
import { filterRows, sortRows, supportedByType, verdictCounts } from "../lib/results";
import { makeRun, mockFetch } from "../test/fixtures";
import { Results } from "./Results";

function row(id: string, status: string, extra: Partial<ResultRow> = {}): ResultRow {
  return {
    requirement_id: id, title: `Title ${id}`, type: id.startsWith("NFR") ? "non-functional" : "functional", subtype: "general",
    verdict: { status, source: "verifier", machine: status }, claims: { supported: 1, total: 2 },
    links: { direct: 1, supporting: 2, total: 3 }, flags: [], human: null, location: {}, verified_at: "2026-10-31T10:00:00Z",
    ...extra,
  };
}

const ROWS = [
  row("FR-001", "supported", { claims: { supported: 2, total: 2 } }),
  row("FR-002", "not_supported_by_candidate", { claims: { supported: 0, total: 3 }, links: { direct: 1, supporting: 5, total: 6 } }),
  row("FR-003", "partially_supported", { flags: [{ code: "edited", label: "Text edited in review", level: "info" }, { code: "unreviewed", label: "Kept without review", level: "warn" }] }),
  row("NFR-001", "supported", { verdict: { status: "supported", source: "human", machine: "not_found", note: "checked" }, human: "Overridden" }),
];
const SUMMARY = { requirements: 4, counts: {}, pending: 0, supported: 2, likely_not_implemented: 1, needs_attention: 1,
  overridden: 1, unreviewed: 1, components: { total: 41, cited_as_evidence: 22 } };

describe("results helpers", () => {
  it("counts, by type, filter and sort", () => {
    expect(verdictCounts(ROWS)).toMatchObject({ supported: 2, partially_supported: 1, not_supported_by_candidate: 1, not_found: 0 });
    expect(supportedByType(ROWS)).toEqual({ functional: { supported: 1, total: 3 }, nonFunctional: { supported: 1, total: 1 } });
    expect(filterRows(ROWS, { verdict: "supported", type: "all", q: "" }).map((r) => r.requirement_id)).toEqual(["FR-001", "NFR-001"]);
    expect(filterRows(ROWS, { verdict: null, type: "nfr", q: "" }).map((r) => r.requirement_id)).toEqual(["NFR-001"]);
    expect(filterRows(ROWS, { verdict: null, type: "all", q: "title fr-002" }).map((r) => r.requirement_id)).toEqual(["FR-002"]);
    expect(sortRows(ROWS, "verdict", 1).map((r) => r.requirement_id)).toEqual(["FR-001", "NFR-001", "FR-003", "FR-002"]);
    expect(sortRows(ROWS, "claims", -1).map((r) => r.requirement_id)[0]).toBe("FR-001");
    expect(sortRows(ROWS, "links", -1)[0].requirement_id).toBe("FR-002");
    expect(sortRows(ROWS, "id", -1).map((r) => r.requirement_id)).toEqual(["NFR-001", "FR-003", "FR-002", "FR-001"]);
  });
});

function setup(routes: Record<string, unknown>, run = { ...makeRun(2, "completed", { finished_at: "2026-10-31T10:28:23Z" }), stages: [], active: false }) {
  const api = mockFetch({ "GET /api/runs/2": run, ...routes });
  vi.stubGlobal("fetch", api.fn);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/runs/2/results"]}>
        <Routes>
          <Route path="/runs/:runId/results" element={<Results />} />
          <Route path="/runs/:runId/requirements/:rid" element={<div>requirement page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return api;
}

afterEach(() => vi.unstubAllGlobals());

describe("Results page", () => {
  it("summary, cards filter the table, rows open the requirement", async () => {
    setup({ "GET /api/runs/2/results": { ready: true, summary: SUMMARY, requirements: ROWS } });
    expect(await screen.findByText("4 of 4 shown")).toBeInTheDocument();
    expect(document.body.textContent).toContain("requirements supported");
    expect(screen.getByText("Text edited in review +1")).toBeInTheDocument();
    expect(screen.getByText("Overridden")).toBeInTheDocument();
    expect(document.body.textContent).toContain("components cited as evidence");
    expect(screen.getByText("19 without evidence →")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Not supported by candidate/ }));
    expect(screen.getByText("1 of 4 shown")).toBeInTheDocument();
    expect(screen.getByText("Verdict: Not supported by candidate")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Clear verdict filter"));
    fireEvent.change(screen.getByLabelText("Search requirements"), { target: { value: "zzz" } });
    expect(screen.getByText(/No requirements match/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Reset filters"));
    fireEvent.click(screen.getByText("Title FR-003"));
    expect(await screen.findByText("requirement page")).toBeInTheDocument();
  });

  it("re-runs verification for the selected rows", async () => {
    const api = setup({
      "GET /api/runs/2/results": { ready: true, summary: SUMMARY, requirements: ROWS },
      "POST /api/runs/2/verify": { run_id: 2, verifying: ["FR-002", "FR-003"] },
    });
    await screen.findByText("4 of 4 shown");
    const rerun = screen.getByRole("button", { name: "Re-run verification" });
    expect(rerun).toBeDisabled();
    fireEvent.click(screen.getByLabelText("Select FR-002"));
    fireEvent.click(screen.getByLabelText("Select FR-003"));
    fireEvent.click(screen.getByRole("button", { name: "Re-run verification (2)" }));
    await waitFor(() => {
      const call = api.calls.find((c) => c.method === "POST");
      expect(JSON.parse(call!.init!.body as string)).toEqual({ requirement_ids: ["FR-002", "FR-003"] });
    });
    expect(await screen.findByText(/Re-verifying 2 requirements/)).toBeInTheDocument();
  });

  it("export menu links to the downloads", async () => {
    setup({ "GET /api/runs/2/results": { ready: true, summary: SUMMARY, requirements: ROWS } });
    await screen.findByText("4 of 4 shown");
    fireEvent.click(screen.getByRole("button", { name: /Export/ }));
    const menu = screen.getByRole("menu");
    expect(within(menu).getByText("CSV").closest("a")).toHaveAttribute("href", "/api/runs/2/export.csv");
    expect(within(menu).getByText("JSON").closest("a")).toHaveAttribute("href", "/api/runs/2/export.json");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("before tracing: points to the pipeline", async () => {
    setup({ "GET /api/runs/2/results": { ready: false, summary: null, requirements: [] } }, { ...makeRun(2, "paused"), stages: [], active: false });
    expect(await screen.findByText(/Results appear once requirements are indexed and verified/)).toBeInTheDocument();
  });

  it("partial results are labelled and re-run is unavailable", async () => {
    setup({ "GET /api/runs/2/results": { ready: true, summary: { ...SUMMARY, pending: 2 }, requirements: ROWS } },
      { ...makeRun(2, "failed"), stages: [], active: false });
    expect(await screen.findByText("Partial results.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Select FR-001"));
    expect(screen.getByRole("button", { name: "Re-run verification (1)" })).toBeDisabled();
  });
});
