import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../components/layout/AppShell";
import { makeRun, mockFetch } from "../test/fixtures";
import { Runs } from "./Runs";
import { queryTerms, Search } from "./Search";

function wrap(node: React.ReactNode, path: string, route: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path={route} element={node} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("delete run modal", () => {
  it("asks in a themed dialog; Keep run does nothing, Delete run deletes", async () => {
    const api = mockFetch({
      "GET /api/runs": { runs: [makeRun(4, "paused"), makeRun(2, "completed", { summary: { requirements: 39, status_counts: { supported: 18 } } })] },
      "DELETE /api/runs/4": { run_id: 4, deleted: true },
    });
    vi.stubGlobal("fetch", api.fn);
    const confirm = vi.fn();
    vi.stubGlobal("confirm", confirm);
    wrap(<Runs />, "/", "/");
    fireEvent.click(await screen.findByLabelText("Delete run 4"));
    expect(screen.getByRole("dialog", { name: "Delete Run #4?" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Keep run" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Keep run" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);

    fireEvent.click(screen.getByLabelText("Delete run 4"));
    fireEvent.click(screen.getByRole("button", { name: "Delete run" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE" && c.url === "/api/runs/4")).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(confirm).not.toHaveBeenCalled();                          // no browser alert any more
  });

  it("shows a failed delete inside the dialog", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "GET /api/runs": { runs: [makeRun(4, "paused")] },
      "DELETE /api/runs/4": () => new Response(JSON.stringify({ detail: "Cancel the run before deleting it" }), { status: 409 }),
    }).fn);
    wrap(<Runs />, "/", "/");
    fireEvent.click(await screen.findByLabelText("Delete run 4"));
    fireEvent.click(screen.getByRole("button", { name: "Delete run" }));
    expect(await screen.findByText("Cancel the run before deleting it")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("collapsible sidebar", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", mockFetch({ "GET /api/runs": { runs: [makeRun(2, "completed")] } }).fn);
  });

  it("collapses to a rail with the button and with [ , and remembers it", async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { unmount } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter><Routes><Route element={<AppShell />}><Route index element={<input aria-label="page input" />} /></Route></Routes></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Runs")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.queryByText("New run")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    expect(localStorage.getItem("tl-sidebar")).toBe("collapsed");

    fireEvent.keyDown(screen.getByLabelText("page input"), { key: "[" });   // typing in a field does not toggle
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "[" });
    expect(screen.getByText("New run")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "[" });
    unmount();

    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter><Routes><Route element={<AppShell />}><Route index element={<div />} /></Route></Routes></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();   // remembered
  });
});

describe("search", () => {
  it("query terms skip filler words", () => {
    expect(queryTerms("The system shall renew a LOAN for members")).toEqual(["renew", "loan", "members"]);
  });

  it("searches as you type and shows requirements with their code, and code with its requirements", async () => {
    const api = mockFetch({
      "GET /api/runs/2/results": { ready: true, summary: null, requirements: [{ requirement_id: "FR-020", title: "Renew a loan" }] },
      "GET /api/runs/2/search": {
        query: "renew a loan", mode: "text", scope: { requirements: true, code: true },
        requirements: [{ requirement_id: "FR-020", title: "Renew a loan", type: "functional", verdict: "supported", score: 0.03,
          match: { keyword: true, semantic: true },
          components: [{ component_id: "lib.models.loan.Loan.renew", role: "direct", path: "lib/models/loan.py", start_line: 25, end_line: 34 },
                       { component_id: "lib.models.loan.Loan", role: "supporting", path: "lib/models/loan.py", start_line: 7, end_line: 37 }] }],
        components: [{ component_id: "lib.models.loan.Loan.renew", type: "method", path: "lib/models/loan.py", start_line: 25, end_line: 34,
          score: 0.01, match: { semantic: true, via_docstring: true },
          requirements: [{ requirement_id: "FR-020", role: "direct", title: "Renew a loan", verdict: "supported" }] },
          { component_id: "lib.util.fmt", type: "function", path: "lib/util.py", start_line: 1, end_line: 2, score: 0.005, match: { keyword: true }, requirements: [] }],
      },
    });
    vi.stubGlobal("fetch", api.fn);
    wrap(<Search />, "/runs/2/search", "/runs/:runId/search");
    expect(await screen.findByText("“Renew a loan”")).toBeInTheDocument();             // example from the run
    fireEvent.change(screen.getByLabelText("Search requirements and code"), { target: { value: "renew a loan" } });
    expect(await screen.findByText("Implemented by", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(api.calls.some((c) => c.url === "/api/runs/2/search?q=renew%20a%20loan&limit=10")).toBe(true);
    expect(screen.getByText("+ 1 supporting component")).toBeInTheDocument();
    expect(screen.getByText("via docstring")).toBeInTheDocument();
    expect(screen.getByText("Not linked to any requirement.")).toBeInTheDocument();
    expect(screen.getAllByText("Loan.renew")[0].closest("a")).toHaveAttribute("href", "/runs/2/code?component=lib.models.loan.Loan.renew");
    expect(screen.getAllByText("renew", { selector: "mark" }).length).toBeGreaterThan(0);  // highlighted
  });

  it("before anything is indexed", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "GET /api/runs/2/results": { ready: false, summary: null, requirements: [] },
      "GET /api/runs/2/search": { query: "x", mode: "empty", requirements: [], components: [], scope: { requirements: false, code: false } },
    }).fn);
    wrap(<Search />, "/runs/2/search?q=fines", "/runs/:runId/search");
    expect(await screen.findByText(/Nothing to search yet/)).toBeInTheDocument();
  });
});
