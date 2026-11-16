import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ReviewItem, ReviewState } from "../api/types";
import { item, makeRun, mockFetch } from "../test/fixtures";
import { Review } from "./Review";

const ITEMS: ReviewItem[] = [
  item("req:1", { category: "incomplete", requirement_id: "FR-021" }, {
    title: "Reject checkout", source_text: "The system shall reject the checkout when:", normalized_text: "The system shall reject a checkout when:",
    reasons: ["The text ends with a colon."], suggestion: { action: "edit" }, location: { paragraph: 31 }, index: 1,
  }),
  item("req:4", { category: "split", requirement_id: "FR-034b" }, {
    title: "Renewal limit", source_text: "A loan may be renewed at most twice.", reasons: ["92% similar to FR-034."],
    suggestion: { action: "merge", target: "FR-034" }, index: 4,
  }),
  item("skip:section:1", { category: "uncertain", resolution: "discarded", resolution_data: { auto: true } }, {
    kind: "skipped_section", title: "1.2 Scope", items: ["Catalog management."], reasons: ["Skipped."],
  }),
];

function state(items: ReviewItem[], extra: Partial<ReviewState> = {}): ReviewState {
  const open = items.filter((i) => !i.resolution);
  return {
    ready: true, status: "waiting", items,
    counts: { total: items.length, resolved: items.length - open.length, open: open.length,
      open_by_category: { uncertain: 0, flagged: 0, incomplete: open.filter((i) => i.category === "incomplete").length, split: open.filter((i) => i.category === "split").length } },
    requirements: [
      { index: 0, requirement_id: "FR-001", title: "Register a member", type: "functional", subtype: "general", location: { paragraph: 5 } },
      { index: 1, requirement_id: "FR-021", title: "Reject checkout", type: "functional", subtype: "general", location: {} },
      { index: 3, requirement_id: "FR-034", title: "Renewal eligibility", type: "functional", subtype: "general", location: {} },
      { index: 4, requirement_id: "FR-034b", title: "Renewal limit", type: "functional", subtype: "general", location: {} },
    ],
    ...extra,
  };
}

function setup(routes: Record<string, unknown>) {
  const api = mockFetch({
    "GET /api/runs/4": { ...makeRun(4, "paused"), stages: [], active: false },
    "GET /api/runs/4/document": { type: "docx", blocks: [{ kind: "paragraph", text: "The system shall reject the checkout when:", level: 1, rows: [], location: { paragraph: 31 } }] },
    "GET /api/runs": { runs: [] },
    ...routes,
  });
  vi.stubGlobal("fetch", api.fn);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/runs/4/review"]}>
        <Routes>
          <Route path="/runs/:runId/review" element={<Review />} />
          <Route path="/runs/:runId/pipeline" element={<div>pipeline page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return api;
}

const put = (api: ReturnType<typeof mockFetch>) => api.calls.filter((c) => c.method === "PUT").map((c) => ({ url: c.url, body: JSON.parse(c.init!.body as string) }));

afterEach(() => vi.unstubAllGlobals());

describe("Review page", () => {
  it("opens on the first tab with open items, shows the reason and the source", async () => {
    setup({ "GET /api/runs/4/review": state(ITEMS) });
    expect(await screen.findByText("The text ends with a colon.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Possibly incomplete/ })).toHaveAttribute("aria-selected", "true");
    expect(document.body.textContent).toContain("1 of 3 reviewed");
    expect(screen.getByRole("button", { name: "Continue tracing →" })).toBeDisabled();
    expect(await screen.findByText(/Showing ¶31 for FR-021/)).toBeInTheDocument();
  });

  it("keyboard: K keeps the focused item, then focus moves on", async () => {
    const api = setup({ "GET /api/runs/4/review": state(ITEMS), "PUT /api/runs/4/review/items/req%3A1": { counts: {} } });
    await screen.findByText("The text ends with a colon.");
    fireEvent.click(screen.getByRole("tab", { name: /All requirements/ }));
    fireEvent.keyDown(window, { key: "k" });
    await waitFor(() => expect(put(api)).toEqual([{ url: "/api/runs/4/review/items/req%3A1", body: { resolution: "kept", data: {} } }]));
    expect(await screen.findByText("Kept FR-021")).toBeInTheDocument();             // toast with undo
  });

  it("edit text: save and keep sends the new text", async () => {
    const api = setup({ "GET /api/runs/4/review": state(ITEMS), "PUT /api/runs/4/review/items/req%3A1": { counts: {} } });
    await screen.findByText("The text ends with a colon.");
    fireEvent.click(screen.getByText("Edit the text"));                              // the suggested fix
    const box = screen.getByLabelText("Requirement text");
    fireEvent.change(box, { target: { value: "The system shall reject a checkout when the member has 5 loans." } });
    fireEvent.click(screen.getByRole("button", { name: "Save and keep" }));
    await waitFor(() => expect(put(api)[0].body).toEqual({ resolution: "edited", data: { text: "The system shall reject a checkout when the member has 5 loans." } }));
  });

  it("merge: the picker ranks targets and a pick merges", async () => {
    const api = setup({
      "GET /api/runs/4/review": state(ITEMS),
      "GET /api/runs/4/review/targets": { targets: [{ requirement_id: "FR-034", title: "Renewal eligibility", similarity: 0.92, suggested: true }] },
      "PUT /api/runs/4/review/items/req%3A4": { counts: {} },
    });
    await screen.findByText("The text ends with a colon.");
    fireEvent.click(screen.getByRole("tab", { name: /Possibly split/ }));
    fireEvent.click(screen.getByRole("button", { name: /Merge into…/ }));
    const listbox = await screen.findByRole("listbox", { name: "Merge target" });
    expect(await within(listbox).findByText("0.92")).toBeInTheDocument();
    fireEvent.change(within(listbox).getByLabelText("Search merge targets"), { target: { value: "register" } });
    expect(within(listbox).getByText("Register a member")).toBeInTheDocument();
    fireEvent.change(within(listbox).getByLabelText("Search merge targets"), { target: { value: "" } });
    fireEvent.click(await within(listbox).findByText("Renewal eligibility"));
    await waitFor(() => expect(put(api)[0]).toEqual({ url: "/api/runs/4/review/items/req%3A4", body: { resolution: "merged", data: { into: "FR-034" } } }));
  });

  it("fix ID is sent with keep", async () => {
    const api = setup({ "GET /api/runs/4/review": state(ITEMS), "PUT /api/runs/4/review/items/req%3A4": { counts: {} } });
    await screen.findByText("The text ends with a colon.");
    fireEvent.click(screen.getByRole("tab", { name: /Possibly split/ }));
    fireEvent.click(screen.getByRole("button", { name: "Fix ID" }));
    const input = screen.getByLabelText("Requirement ID");
    fireEvent.change(input, { target: { value: "FR-037" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("FR-037")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /^Keep/ }));
    await waitFor(() => expect(put(api)[0].body).toEqual({ resolution: "kept", data: { requirement_id: "FR-037" } }));
  });

  it("restores an auto-skipped item", async () => {
    const api = setup({ "GET /api/runs/4/review": state(ITEMS), "DELETE /api/runs/4/review/items/skip%3Asection%3A1": { counts: {} } });
    await screen.findByText("The text ends with a colon.");
    fireEvent.click(screen.getByRole("tab", { name: /All requirements/ }));
    expect(screen.getByText("Skipped automatically")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("nothing open: continue completes the review and opens the pipeline", async () => {
    const done = ITEMS.map((i) => ({ ...i, resolution: i.resolution ?? ("kept" as const) }));
    const api = setup({ "GET /api/runs/4/review": state(done), "POST /api/runs/4/review/complete": { requirements: 4 } });
    expect(await screen.findByText("All blocking items resolved")).toBeInTheDocument();
    expect(screen.getByText(/4 requirements will be traced/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "Continue tracing →" })[0]);
    expect(await screen.findByText("pipeline page")).toBeInTheDocument();
    expect(api.calls.some((c) => c.url === "/api/runs/4/review/complete")).toBe(true);
  });

  it("shows the server's refusal and the items it names", async () => {
    const done = ITEMS.map((i) => ({ ...i, resolution: i.resolution ?? ("kept" as const) }));
    setup({
      "GET /api/runs/4/review": state(done),
      "POST /api/runs/4/review/complete": () => new Response(JSON.stringify({ detail: "IDs used twice: FR-034", keys: ["req:4"] }), { status: 409 }),
    });
    await screen.findByText("All blocking items resolved");
    fireEvent.click(screen.getAllByRole("button", { name: "Continue tracing →" })[0]);
    expect(await screen.findByText(/IDs used twice: FR-034/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "req:4" })).toBeInTheDocument();
  });

  it("not ready while the SRS is still being extracted", async () => {
    setup({ "GET /api/runs/4/review": { ...state([]), ready: false } });
    expect(await screen.findByText(/still extracting requirements/)).toBeInTheDocument();
  });
});
