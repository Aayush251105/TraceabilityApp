import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CodeView as CodeViewData } from "../api/types";
import { fileSize } from "../components/ui/DropZone";
import { makeRun, mockFetch } from "../test/fixtures";
import { CodeView, commonRoot } from "./CodeView";
import { Settings } from "./Settings";

afterEach(() => vi.unstubAllGlobals());

function renderAt(path: string, route: string, element: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path={route} element={element} />
          <Route path="/runs/:runId/requirements/:rid" element={<div>requirement page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Code view
// ---------------------------------------------------------------------------

const CODE: CodeViewData = {
  components: 3, traced: 1,
  files: [
    { path: "shop/cart.py", traced: 1, total: 2, components: [
      { component_id: "shop.cart.Cart.add_item", name: "Cart.add_item", type: "method", start_line: 8, end_line: 11, traced: true,
        requirements: [{ requirement_id: "FR-001", role: "direct", link_status: "supported", verdict: "supported" }], best_candidate: null },
      { component_id: "shop.cart.Cart.total", name: "Cart.total", type: "method", start_line: 13, end_line: 14, traced: false,
        requirements: [], best_candidate: { requirement_id: "FR-002", score: 0.012, rank: 6 } },
    ] },
    { path: "shop/util.py", traced: 0, total: 1, components: [
      { component_id: "shop.util.fmt", name: "util.fmt", type: "function", start_line: 1, end_line: 2, traced: false, requirements: [], best_candidate: null },
    ] },
  ],
};

const componentDetail = (id: string) => ({
  component_id: id, name: id.split(".").slice(-2).join("."), type: "method", path: "shop/cart.py", start_line: 8, end_line: 9,
  signature: null, docstrings: { generated: "Adds an item." }, requirements: [], best_candidate: null,
  code: [{ n: 8, text: "def add_item(self):" }, { n: 9, text: "    pass" }],
});

describe("code view", () => {
  it("common root of file paths", () => {
    expect(commonRoot(["library_system/models/book.py", "library_system/main.py"])).toBe("library_system/");
    expect(commonRoot(["a.py", "b/c.py"])).toBe("");
    expect(commonRoot([])).toBe("");
  });

  it("opens on the first traced component, lists its requirements, filters untraced code", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "GET /api/runs/2": { ...makeRun(2, "completed"), stages: [{ stage: "index_code", detail: { report: { relationships: 58 } } }], active: false },
      "GET /api/runs/2/results": { ready: true, summary: null, requirements: [{ requirement_id: "FR-001", title: "Add an item" }, { requirement_id: "FR-002", title: "Cart total" }] },
      "GET /api/runs/2/code": CODE,
      "GET /api/runs/2/code/component": componentDetail("shop.cart.Cart.add_item"),
    }).fn);
    renderAt("/runs/2/code", "/runs/:runId/code", <CodeView />);
    expect(await screen.findByRole("heading", { name: "Cart.add_item" })).toBeInTheDocument();
    expect(screen.getByText("Traced · 1 requirement")).toBeInTheDocument();
    expect(await screen.findByText("Add an item")).toBeInTheDocument();
    expect(screen.getByText(/58 relationships/)).toBeInTheDocument();
    expect(await screen.findByText("Adds an item.")).toBeInTheDocument();
    expect(screen.getByText("def add_item(self):")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Untraced code/ }));
    expect(screen.queryByText("Cart.add_item", { selector: "nav span" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("Cart.total", { selector: "nav span" }));
    expect(await screen.findByText("No requirement maps to this component")).toBeInTheDocument();
    expect(screen.getByText("FR-002")).toHaveAttribute("href", "/runs/2/requirements/FR-002");
    expect(screen.getByText(/at rank #6/)).toBeInTheDocument();
  });

  it("preselects the component in the URL", async () => {
    vi.stubGlobal("fetch", mockFetch({
      "GET /api/runs/2": { ...makeRun(2, "completed"), stages: [], active: false },
      "GET /api/runs/2/results": { ready: true, summary: null, requirements: [] },
      "GET /api/runs/2/code": CODE,
      "GET /api/runs/2/code/component": componentDetail("shop.util.fmt"),
    }).fn);
    renderAt("/runs/2/code?component=shop.util.fmt", "/runs/:runId/code", <CodeView />);
    expect(await screen.findByRole("heading", { name: "util.fmt" })).toBeInTheDocument();
    expect(screen.getByText(/No requirement ranked it/)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

const SETTINGS = {
  models: { docagent: "yi-coder:9b", srs: "llama3.1", judge: "qwen2.5:3b", verifier: "qwen2.5-coder:14b" },
  ollama_host: "http://localhost:11434",
  ingest: { parallel: true, overwrite_docstrings: true },
  search: { top_n: 10, candidate_k: 50 },
  mapping: { max_direct_rank: 3, max_supporting: 6, use_source_references: true },
  verification: { claims: "clauses" },
  review: { duplicate_threshold: 0.9 },
  limits: { max_upload_mb: 200, large_repo_files: 400, large_repo_components: 1500 },
  source: { exclude_dirs: ["venv", ".git"] },
};
const HEALTH = {
  agents: { docagent: { dir: "C:/DocAgent", python: "py", dir_ok: true, python_ok: true }, srsagent: { dir: "C:/SRSAgent", python: "py", dir_ok: true, python_ok: false } },
  ollama_host: "http://localhost:11434",
  embeddings: { model: "sentence-transformers/all-MiniLM-L6-v2", dim: 384, local: true },
  database: { ok: true, connection: "postgresql://postgres@localhost:5432/traceability_dev", pgvector: "0.8.1", bytes: 14_900_000, latency_ms: 3 },
  ollama: { ok: true, version: "0.34.4", models: ["yi-coder:9b", "llama3.1:latest", "qwen2.5:3b", "qwen2.5-coder:7b"],
    details: [{ name: "yi-coder:9b", size: 5_038_000_000 }, { name: "llama3.1:latest", size: 4_920_000_000 }] },
  models: {},
};

describe("settings", () => {
  it("file sizes", () => {
    expect(fileSize(5_038_000_000)).toBe("4.7 GB");
    expect(fileSize(14_900_000)).toBe("14.2 MB");
  });

  it("shows model status, a missing model with its pull command, database and agents", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/settings": { settings: SETTINGS, defaults: SETTINGS }, "GET /api/health": HEALTH }).fn);
    renderAt("/settings", "/settings", <Settings />);
    expect(await screen.findByText("Connected · 1 model missing")).toBeInTheDocument();
    expect(screen.getByText("ollama pull qwen2.5-coder:14b")).toBeInTheDocument();
    expect(screen.getByText("4.7 GB")).toBeInTheDocument();
    expect(screen.getByText("pgvector 0.8.1")).toBeInTheDocument();
    expect(screen.getByText(".venv missing")).toBeInTheDocument();
    expect(screen.getByText("384 dims")).toBeInTheDocument();
  });

  it("changes are saved together; discard restores", async () => {
    const api = mockFetch({
      "GET /api/settings": { settings: SETTINGS, defaults: SETTINGS },
      "GET /api/health": HEALTH,
      "PUT /api/settings": (init?: RequestInit) => ({ settings: JSON.parse(init!.body as string) }),
    });
    vi.stubGlobal("fetch", api.fn);
    renderAt("/settings", "/settings", <Settings />);
    const save = await screen.findByRole("button", { name: "Save settings" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Verification model"), { target: { value: "qwen2.5-coder:7b" } });
    fireEvent.click(screen.getByLabelText(/SRS first, then code/));
    fireEvent.click(screen.getByLabelText("Remove venv"));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    fireEvent.click(save);
    await waitFor(() => {
      const body = JSON.parse(api.calls.find((c) => c.method === "PUT")!.init!.body as string);
      expect(body.models.verifier).toBe("qwen2.5-coder:7b");
      expect(body.ingest.parallel).toBe(false);
      expect(body.source.exclude_dirs).toEqual([".git"]);
    });
    expect(await screen.findByText(/Settings saved/)).toBeInTheDocument();
  });

  it("test connection checks the typed endpoint and reports when it is down", async () => {
    const api = mockFetch({
      "GET /api/settings": { settings: SETTINGS, defaults: SETTINGS },
      "GET /api/health": HEALTH,
    });
    const fn = vi.fn(async (url: string, init?: RequestInit) =>
      url.includes("host=") ? new Response(JSON.stringify({ ...HEALTH, ollama_host: "http://gpu:11434", ollama: { ok: false, error: "refused" } })) : api.fn(url, init));
    vi.stubGlobal("fetch", fn);
    renderAt("/settings", "/settings", <Settings />);
    await screen.findByText("Connected · 1 model missing");
    fireEvent.change(screen.getByDisplayValue("http://localhost:11434"), { target: { value: "http://gpu:11434" } });
    fireEvent.click(screen.getByRole("button", { name: "Test connection" }));
    expect(await screen.findByText("Can’t reach Ollama at gpu:11434.")).toBeInTheDocument();
    expect(fn.mock.calls.some(([u]) => String(u) === "/api/health?host=http%3A%2F%2Fgpu%3A11434")).toBe(true);
  });
});
