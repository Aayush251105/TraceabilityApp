import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../components/layout/AppShell";
import { makeRun, mockFetch } from "../test/fixtures";
import { Runs } from "./Runs";
import { linesLabel, queryTerms, Search } from "./Search";

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

  it("searches on Enter (not while typing) and shows requirements with their code, and code with its requirements", async () => {
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
    const box = screen.getByLabelText("Search requirements and code");
    fireEvent.change(box, { target: { value: "renew a loan" } });
    expect(screen.getByText(/to search/)).toBeInTheDocument();                         // hint, no request yet
    await new Promise((r) => setTimeout(r, 600));
    expect(api.calls.some((c) => c.url.startsWith("/api/runs/2/search"))).toBe(false);
    fireEvent.submit(box.closest("form")!);
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

const RESULTS = { ready: true, summary: null, requirements: [{ requirement_id: "FR-016", title: "Check out a book" }] };

describe("ask", () => {
  it("lines label", () => {
    expect(linesLabel([12])).toBe("line 12");
    expect(linesLabel([12, 40])).toBe("lines 12, 40");
    expect(linesLabel(undefined)).toBe("");
  });

  it("switches to Ask, asks on Enter, and shows the answer with callers, lines and requirements", async () => {
    const api = mockFetch({
      "GET /api/runs/2/results": RESULTS,
      "GET /api/runs/2/ask": {
        question: "which functions use can_borrow()?", intent: "callers", target: "can_borrow", parsed_by: "rules",
        answer: "2 components use can_borrow.", note: "Calls made through dynamic dispatch may be missed.",
        matches: [{ component_id: "lib.models.member.Member.can_borrow", name: "Member.can_borrow", type: "method", path: "lib/models/member.py", start_line: 20, end_line: 21, requirements: [] }],
        components: [
          { component_id: "lib.models.loan.Loan.renew", name: "Loan.renew", type: "method", path: "lib/models/loan.py", start_line: 30, end_line: 33,
            relation: "calls Member.can_borrow", lines: [31], requirements: [] },
          { component_id: "lib.services.lending.LendingService.checkout", name: "LendingService.checkout", type: "method", path: "lib/services/lending.py",
            start_line: 10, end_line: 15, relation: "calls Member.can_borrow", lines: [12, 14],
            requirements: [{ requirement_id: "FR-016", role: "direct", title: "Check out a book", verdict: "supported" }] },
        ],
        requirements: [],
      },
    });
    vi.stubGlobal("fetch", api.fn);
    wrap(<Search />, "/runs/2/search", "/runs/:runId/search");
    fireEvent.click(await screen.findByRole("tab", { name: "Ask" }));
    expect(screen.getByRole("tab", { name: "Ask" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("“which functions use can_borrow()?”")).toBeInTheDocument();     // ask examples
    const box = screen.getByLabelText("Ask a question about this run");
    fireEvent.change(box, { target: { value: "which functions use can_borrow()?" } });
    expect(screen.getByText(/to ask/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.url.startsWith("/api/runs/2/ask"))).toBe(false);
    fireEvent.submit(box.closest("form")!);

    expect(await screen.findByText("2 components use can_borrow.")).toBeInTheDocument();
    expect(api.calls.some((c) => c.url === "/api/runs/2/ask?q=which%20functions%20use%20can_borrow()%3F&limit=10")).toBe(true);
    expect(api.calls.some((c) => c.url.startsWith("/api/runs/2/search"))).toBe(false);
    expect(screen.getByText("Who uses")).toBeInTheDocument();
    expect(screen.getByText(/understood from the wording/)).toBeInTheDocument();
    expect(screen.getByText("Member.can_borrow").closest("a")).toHaveAttribute("href", "/runs/2/code?component=lib.models.member.Member.can_borrow");
    expect(screen.getByText("Used by")).toBeInTheDocument();
    expect(screen.getByText("calls Member.can_borrow · lines 12, 14")).toBeInTheDocument();
    expect(screen.getByText("LendingService.checkout").closest("a")).toHaveAttribute("href", "/runs/2/code?component=lib.services.lending.LendingService.checkout");
    expect(screen.getByText("FR-016").closest("a")).toHaveAttribute("href", "/runs/2/requirements/FR-016");
    expect(screen.getByText(/dynamic dispatch/)).toBeInTheDocument();
  });

  it("describe shows the summary and where it came from; requirement lists show their code", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "GET /api/runs/2/results": RESULTS,
      "GET /api/runs/2/ask": {
        question: "what does checkout do?", intent: "describe", target: "checkout", parsed_by: "llm", answer: "Lends a book to a member.",
        matches: [{ component_id: "lib.services.lending.LendingService.checkout", name: "LendingService.checkout", type: "method", path: "lib/services/lending.py",
          start_line: 10, end_line: 15, summary: "Lends a book to a member.", summary_kind: "generated",
          requirements: [{ requirement_id: "FR-016", role: "direct", title: "Check out a book", verdict: "supported" }] }],
        components: [],
        requirements: [{ requirement_id: "FR-016", title: "Check out a book", verdict: "supported",
          components: [{ component_id: "lib.services.lending.LendingService.checkout", role: "direct", path: "lib/services/lending.py", start_line: 10, end_line: 15 },
                       { component_id: "lib.services.lending.LendingService", role: "supporting", path: "lib/services/lending.py", start_line: 1, end_line: 30 }] }],
      },
    }).fn);
    wrap(<Search />, "/runs/2/search?mode=ask&q=what%20does%20checkout%20do%3F", "/runs/:runId/search");
    expect(await screen.findByText("Matched code")).toBeInTheDocument();
    expect(screen.getByText("What it does")).toBeInTheDocument();
    expect(screen.getByText(/understood by the local model/)).toBeInTheDocument();
    expect(screen.getByText("(generated description, may be imprecise)")).toBeInTheDocument();
    expect(screen.getByText("Implemented by")).toBeInTheDocument();
    expect(screen.getByText("+ 1 supporting component")).toBeInTheDocument();
  });

  it("an unrecognised question falls back to the normal search results", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "GET /api/runs/2/results": RESULTS,
      "GET /api/runs/2/ask": {
        question: "cart things", intent: "find", target: "cart things", parsed_by: "fallback",
        answer: "No specific question type was recognised, so these are the search results.",
        matches: [], components: [], requirements: [],
        search: { query: "cart things", mode: "text", scope: { requirements: true, code: true }, requirements: [],
          components: [{ component_id: "shop.Cart.total", type: "method", path: "shop.py", start_line: 3, end_line: 5, score: 0.1, match: { keyword: true }, requirements: [] }] },
      },
    }).fn);
    wrap(<Search />, "/runs/2/search?mode=ask&q=cart%20things", "/runs/:runId/search");
    expect(await screen.findByText(/so these are the search results/)).toBeInTheDocument();
    expect(screen.getByText(/not understood, so searched instead/)).toBeInTheDocument();
    expect(screen.getByText("No requirement matches “cart things”.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cart.total" })).toHaveAttribute("href", "/runs/2/code?component=shop.Cart.total");
  });
});
