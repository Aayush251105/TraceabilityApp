import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { VERDICTS } from "../lib/status";
import { Sidebar } from "./layout/Sidebar";
import { CodeBlock } from "./ui/Code";
import { ProgressBar } from "./ui/Progress";
import { StatusChip } from "./ui/Status";
import { ClaimItem } from "./ui/Trace";

describe("ui", () => {
  it("status chip shows label and glyph", () => {
    render(<StatusChip meta={VERDICTS.not_supported_by_candidate} />);
    expect(screen.getByText("Not supported by candidate")).toBeInTheDocument();
    expect(screen.getByText("✕")).toBeInTheDocument();
  });

  it("progress bar exposes its value", () => {
    render(<ProgressBar value={0.444} label="Overall" />);
    expect(screen.getByRole("progressbar", { name: "Overall" })).toHaveAttribute("aria-valuenow", "44");
    render(<ProgressBar label="Estimating" />);
    expect(screen.getByRole("progressbar", { name: "Estimating" })).not.toHaveAttribute("aria-valuenow");
  });

  it("code block highlights cited lines with their claim marker", () => {
    const { container } = render(
      <CodeBlock
        lines={[{ n: 21, text: "def a():" }, { n: 22, text: "    return 1" }]}
        highlights={{ 22: { meta: VERDICTS.supported, mark: "C1" } }}
      />,
    );
    const cited = container.querySelector('[data-line="22"]') as HTMLElement;
    expect(cited.style.background).toContain("--ok-bg");
    expect(screen.getByText("C1")).toBeInTheDocument();
    expect(screen.getByText("21")).toBeInTheDocument();
  });

  it("claim citations are clickable without selecting the claim", () => {
    const onCite = vi.fn();
    const onSelect = vi.fn();
    render(
      <ClaimItem tag="C1" text="Claim" verdict="supported" citations={[{ label: "a.py:1-2", onClick: onCite }]}
        discarded={[{ label: "b.py:3", reason: "never read" }]} onSelect={onSelect} />,
    );
    fireEvent.click(screen.getByText("a.py:1-2"));
    expect(onCite).toHaveBeenCalledOnce();
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByText(/never read/)).toBeInTheDocument();
  });
});

describe("sidebar", () => {
  afterEach(() => vi.unstubAllGlobals());

  function mockApi(routes: Record<string, unknown>) {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      const body = routes[url];
      return new Response(JSON.stringify(body ?? { detail: "not found" }), { status: body ? 200 : 404 });
    }));
  }

  const run = (id: number, status: string, extra: object = {}) => ({
    run_id: id, name: `Run ${id}`, status, error: null,
    source: { kind: "folder", ref: "x", git_ref: null, commit_sha: id === 14 ? "4f2a9c1abc" : null },
    srs_filename: "srs.docx", document_id: null, repo_id: null, created_at: "2026-10-31T10:00:00Z",
    started_at: null, finished_at: null, summary: {}, models: null,
    progress: { fraction: 0, remaining_seconds: null }, rail: [],
    review: { total: 7, resolved: 0, open: 0, open_by_category: {} }, ...extra,
  });

  it("shows the current run, its review badge, recent runs and Ollama status", async () => {
    mockApi({
      "/api/runs": { runs: [
        run(14, "paused", { review: { total: 7, resolved: 0, open: 7, open_by_category: {} } }),
        run(12, "completed", { summary: { requirements: 39, status_counts: { supported: 31 } } }),
        run(11, "failed"),
      ] },
      "/api/health": { agents: {}, ollama_host: "http://localhost:11434", database: { ok: true },
                       ollama: { ok: true, models: [] }, models: {} },
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/runs/14/pipeline"]}>
          <Sidebar />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getAllByText("Run #14")).toHaveLength(2));   // section header + recent runs
    expect(screen.getByText("4f2a9c1")).toBeInTheDocument();
    expect(screen.getByText("7")).toBeInTheDocument();                    // review badge
    expect(screen.getByText("31/39")).toBeInTheDocument();                // completed run: supported/total
    expect(screen.getByText("Needs input")).toBeInTheDocument();
    expect(screen.getByText("Live pipeline").closest("a")).toHaveAttribute("href", "/runs/14/pipeline");
    await waitFor(() => expect(screen.getByText("Ollama connected · localhost")).toBeInTheDocument());
  });

  it("says when the server is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("network"); }));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Sidebar />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(screen.getByText("Server unreachable")).toBeInTheDocument());
  });
});
