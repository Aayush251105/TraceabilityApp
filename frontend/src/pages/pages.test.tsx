import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { makeRun, mockFetch } from "../test/fixtures";
import { NewRun } from "./NewRun";
import { Runs } from "./Runs";

const SETTINGS = {
  settings: {
    models: { docagent: "yi-coder:9b", srs: "llama3.1", judge: "qwen2.5:3b", verifier: "qwen2.5-coder:7b" },
    ollama_host: "http://localhost:11434",
    ingest: { parallel: true, overwrite_docstrings: true },
    search: { top_n: 10, candidate_k: 50 },
    mapping: { max_direct_rank: 3, max_supporting: 6, use_source_references: true },
    verification: { claims: "clauses" },
    review: { duplicate_threshold: 0.9 },
    limits: { max_upload_mb: 200, large_repo_files: 400, large_repo_components: 1500 },
    source: { exclude_dirs: ["venv", ".git"] },
  },
};
const HEALTH = { agents: {}, ollama_host: "http://localhost:11434", database: { ok: true },
  ollama: { ok: true, models: ["yi-coder:9b", "llama3.1:latest", "qwen2.5:3b", "qwen2.5-coder:7b", "qwen2.5-coder:14b"] }, models: {} };
const STATS = { files: 13, python_files: 11, python_lines: 1284, bytes: 88000, classes: 5, functions: 9, methods: 27, components: 41, unparsable: [] };

function renderAt(path: string, element: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={element} />
          <Route path="/new" element={element} />
          <Route path="/runs/:id/pipeline" element={<div>pipeline page</div>} />
          <Route path="/runs/:id/review" element={<div>review page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("Runs page", () => {
  it("first use shows the empty state", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/runs": { runs: [] } }).fn);
    renderAt("/", <Runs />);
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(screen.getByText("New traceability run").closest("a")).toHaveAttribute("href", "/new");
  });

  it("lists runs, filters them and opens a run where it needs the user", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/runs": { runs: [
      makeRun(3, "paused", { review: { total: 7, resolved: 0, open: 7, open_by_category: {} } }),
      makeRun(2, "completed", { summary: { requirements: 39, status_counts: { supported: 18 } }, finished_at: "2026-10-31T09:20:00Z" }),
      makeRun(1, "failed", { error: "Cannot start: Ollama is not reachable." }),
    ] } }).fn);
    renderAt("/", <Runs />);
    expect(await screen.findByText("18 / 39 supported")).toBeInTheDocument();
    expect(screen.getByText("7 items to review")).toBeInTheDocument();
    expect(screen.getByText("20:00")).toBeInTheDocument();                      // duration of run 2
    fireEvent.click(screen.getByRole("tab", { name: /Failed/ }));
    expect(screen.queryByText("18 / 39 supported")).not.toBeInTheDocument();
    expect(screen.getByText("Cannot start: Ollama is not reachable.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: /All/ }));
    fireEvent.change(screen.getByLabelText("Search runs"), { target: { value: "nothing like this" } });
    expect(screen.getByText(/No runs match/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Show all runs"));
    fireEvent.click(screen.getByText("7 items to review"));
    expect(await screen.findByText("review page")).toBeInTheDocument();
  });

  it("shows a load error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    renderAt("/", <Runs />);
    expect(await screen.findByText(/Cannot reach the Tracelight server/)).toBeInTheDocument();
  });
});

describe("New run page", () => {
  it("needs both inputs, checks the folder, then starts and opens the pipeline", async () => {
    const api = mockFetch({
      "GET /api/settings": SETTINGS,
      "GET /api/health": HEALTH,
      "POST /api/inspect": { kind: "folder", stats: STATS, warnings: [] },
      "POST /api/runs": makeRun(7, "running"),
    });
    vi.stubGlobal("fetch", api.fn);
    renderAt("/new", <NewRun />);
    const start = await screen.findByRole("button", { name: "Start traceability run" });
    expect(start).toBeDisabled();
    expect(screen.getByText("Add a requirements document and a codebase to start.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Paste text" }));
    fireEvent.change(screen.getByLabelText("SRS text"), { target: { value: "FR-001 The system shall add a book." } });
    fireEvent.click(screen.getByRole("tab", { name: "Folder" }));
    fireEvent.change(screen.getByPlaceholderText("C:\\path\\to\\project"), { target: { value: "C:\\code\\library" } });

    expect(await screen.findByText("Ready: 11 Python files, 41 components.")).toBeInTheDocument();
    expect(screen.getAllByText("~27 min")).toHaveLength(2);                          // 41 × 40 s: plan + estimate
    await waitFor(() => expect(start).toBeEnabled());

    const inspectCall = api.calls.find((c) => c.url === "/api/inspect")!;
    const inspectForm = inspectCall.init!.body as FormData;
    expect(inspectForm.get("folder")).toBe("C:\\code\\library");
    expect(JSON.parse(inspectForm.get("exclude_dirs") as string)).toEqual(["venv", ".git"]);

    fireEvent.click(start);
    expect(await screen.findByText("pipeline page")).toBeInTheDocument();
    const form = api.calls.find((c) => c.url === "/api/runs" && c.method === "POST")!.init!.body as FormData;
    expect(form.get("source_kind")).toBe("folder");
    expect((form.get("srs") as File).name).toBe("pasted_srs.md");
    expect(JSON.parse(form.get("overrides") as string)).toEqual({
      models: SETTINGS.settings.models, source: { exclude_dirs: ["venv", ".git"] }, ingest: { parallel: true } });
  });

  it("rejects an unsupported SRS file and a bad repository URL", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/settings": SETTINGS, "GET /api/health": HEALTH }).fn);
    const { container } = renderAt("/new", <NewRun />);
    await screen.findByRole("button", { name: "Start traceability run" });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(["MZ"], "setup.exe")] } });
    expect(await screen.findByText(/setup.exe is not a supported format/)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("https://github.com/owner/repo"), { target: { value: "git@github.com:a/b.git" } });
    expect(screen.getByText("Not a repository URL.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start traceability run" })).toBeDisabled();
  });

  it("shows the large-repository warning and the server's no-python error", async () => {
    let answer: unknown = { kind: "folder", stats: { ...STATS, python_files: 1842, components: 6900 },
      warnings: [{ code: "large_repo", level: "warn", message: "1842 Python files." }] };
    vi.stubGlobal("fetch", mockFetch({ "GET /api/settings": SETTINGS, "GET /api/health": HEALTH, "POST /api/inspect": () => answer }).fn);
    renderAt("/new", <NewRun />);
    await screen.findByRole("button", { name: "Start traceability run" });
    fireEvent.click(screen.getByRole("tab", { name: "Folder" }));
    fireEvent.change(screen.getByPlaceholderText("C:\\path\\to\\project"), { target: { value: "C:\\big" } });
    expect(await screen.findByText("Large repository.")).toBeInTheDocument();
    expect(screen.getByText(/would take about 76 h 40 min/)).toBeInTheDocument();     // 6,900 × 40 s
    answer = { kind: "folder", stats: { ...STATS, python_files: 0, components: 0 },
      warnings: [{ code: "no_python", level: "error", message: "No Python files found." }] };
    fireEvent.change(screen.getByPlaceholderText("C:\\path\\to\\project"), { target: { value: "C:\\docs" } });
    expect(await screen.findByText("No Python files found.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start traceability run" })).toBeDisabled();
  });
});
