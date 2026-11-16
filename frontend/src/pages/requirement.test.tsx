import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RequirementDetail } from "../api/types";
import {
  citationLabel, claimMeta, codeSpans, discardedLabel, edgeLabel, layoutGraph, lineMarks, tagMap, whyRows,
} from "../lib/requirement";
import { makeRun, mockFetch } from "../test/fixtures";
import { Requirement } from "./Requirement";

const CHECKOUT = "library_system.services.lending.LendingService.checkout";
const CAN_BORROW = "library_system.models.member.Member.can_borrow";

function detail(extra: Partial<RequirementDetail> = {}): RequirementDetail {
  return {
    requirement: { requirement_id: "FR-016", title: "Check out a book", type: "functional", subtype: "transaction",
      raw_text: "The system shall check out a book.", normalized_text: "", location: { paragraph: 52, section: "3.4 Lending" },
      sub_requirements: [], conditions: [], error_conditions: [], review: {} },
    verdict: { status: "partially_supported", source: "verifier", machine: "partially_supported" },
    flags: [{ code: "incomplete_text", label: "Requirement text looks incomplete", level: "warn" }],
    verification: { status: "partially_supported", rationale: "[requirement text looks incomplete: x] Claim 1 holds; `renew` is missing.",
      model: "qwen2.5-coder:7b", prompt_version: "verify-v2.3", created_at: "2026-10-31T10:00:00Z", incomplete_text: true },
    claims: [
      { claim_id: "c1", text: "Only members in good standing can borrow.", verdict: "supported", model_verdict: "supported",
        rationale: "`checkout` calls `can_borrow`.", evidence: [
          { component_id: CHECKOUT, path: "library_system/services/lending.py", start_line: 25, end_line: 26, quote: "if not member.can_borrow():", tag: "C1" },
          { component_id: CAN_BORROW, path: "library_system/models/member.py", start_line: 17, end_line: 20, tag: "C2" }],
        rejected: [] },
      { claim_id: "c2", text: "Members with fines cannot renew.", verdict: "not_supported", model_verdict: "not_supported",
        rationale: "No fine check.", evidence: [],
        rejected: [{ reference: { component: "C2", start_line: 15, end_line: 15 }, reason: "C2: quote not found nearby" }] },
    ],
    components: [
      { component_id: CHECKOUT, name: "LendingService.checkout", type: "method", role: "direct", status: "supported", rank: 1, reason: null,
        path: "library_system/services/lending.py", start_line: 21, end_line: 27, docstring: { kind: "generated", content: "Checks out a copy." },
        scores: { fused: 0.016, channels: { component_lexical: { rank: 1, score: 0.0057 }, component_vector: { rank: 2, score: 0.62 } } },
        code: Array.from({ length: 7 }, (_, i) => ({ n: 21 + i, text: `line ${21 + i}` })) },
      { component_id: CAN_BORROW, name: "Member.can_borrow", type: "method", role: "supporting", status: "pending_verification", rank: null,
        reason: "called by LendingService.checkout", path: "library_system/models/member.py", start_line: 17, end_line: 20, docstring: null,
        scores: { fused: null, channels: {} }, code: Array.from({ length: 4 }, (_, i) => ({ n: 17 + i, text: `member ${17 + i}` })) },
    ],
    edges: [{ from: CHECKOUT, to: CAN_BORROW, type: "calls", source: "docagent" }],
    search: [
      { component_id: CHECKOUT, name: "LendingService.checkout", rank: 1, fused: 0.016, channels: {}, mapped: true },
      { component_id: "x.Loan.renew", name: "Loan.renew", rank: 2, fused: 0.012, channels: { component_vector: { rank: 3, score: 0.5 } }, mapped: false },
    ],
    history: [
      { kind: "override", status: "supported", note: "Checked the call path by hand", at: "2026-10-31T11:00:00Z" },
      { kind: "verification", status: "partially_supported", model: "qwen2.5-coder:7b", claims: { supported: 1, total: 2 }, at: "2026-10-31T10:00:00Z" },
    ],
    ...extra,
  };
}

describe("requirement helpers", () => {
  it("claim vocabulary, inline code, labels", () => {
    expect(claimMeta("not_supported").label).toBe("Not supported");
    expect(claimMeta("supported").label).toBe("Supported");
    expect(codeSpans("`a` calls `b`.")).toEqual([{ code: true, text: "a" }, { code: false, text: " calls " }, { code: true, text: "b" }, { code: false, text: "." }]);
    expect(citationLabel("library_system/models/member.py", 17, 20)).toBe("member.py:17-20");
    expect(citationLabel("a/b.py", 5, 5)).toBe("b.py:5");
    expect(edgeLabel("call_reference")).toBe("calls");
  });

  it("cited lines take the claim's colour and a marker on the first line", () => {
    const d = detail();
    const marks = lineMarks(d.claims, CHECKOUT, null);
    expect(Object.keys(marks).map(Number)).toEqual([25, 26]);
    expect(marks[25].mark).toBe("C1");
    expect(marks[26].mark).toBeUndefined();
    expect(marks[25].meta.label).toBe("Supported");
  });

  it("the active claim wins a line cited by two claims", () => {
    const claims = [
      { ...detail().claims[0], evidence: [{ component_id: "c", path: "p.py", start_line: 1, end_line: 2 }] },
      { ...detail().claims[1], evidence: [{ component_id: "c", path: "p.py", start_line: 2, end_line: 3 }] },
    ];
    expect(lineMarks(claims, "c", null)[2].claim).toBe(0);
    expect(lineMarks(claims, "c", 1)[2].claim).toBe(1);
  });

  it("discarded evidence resolves the verifier's tag to a file", () => {
    const d = detail();
    expect(discardedLabel(d.claims[1].rejected[0].reference, tagMap(d.claims), d.components)).toBe("member.py:15");
    expect(discardedLabel({ component: "C9", start_line: 3, end_line: 4 }, {}, [])).toBe("C9:3-4");
  });

  it("graph: three columns spread across the width, labels kept apart", () => {
    const g = layoutGraph(detail(), 800);
    expect(g.width).toBe(800);
    const [req, direct, supporting] = g.nodes;
    expect([req.kind, direct.kind, supporting.kind]).toEqual(["REQUIREMENT", "DIRECT", "SUPPORTING"]);
    expect(supporting.x + supporting.w).toBe(800);
    expect(g.edges.map((e) => e.label)).toEqual(["maps to", "calls"]);
    expect(layoutGraph(detail(), 300).width).toBe(640);                 // never narrower than the minimum
  });

  it("why rows: mapped components, then search candidates not selected", () => {
    const rows = whyRows(detail());
    expect(rows.map((r) => [r.name, r.role, r.rank])).toEqual([
      ["LendingService.checkout", "Direct", "#1"], ["Member.can_borrow", "Supporting", "—"], ["Loan.renew", "Not selected", "#2"]]);
    expect(rows[0].keyword).toBe("0.006");
    expect(rows[0].semantic).toBe("0.62");
    expect(rows[1].because).toBe("called by LendingService.checkout");
  });
});

// ---------------------------------------------------------------------------

afterEach(() => vi.unstubAllGlobals());

function setup(d: RequirementDetail, extra: Record<string, unknown> = {}, run: object = { ...makeRun(2, "completed"), stages: [], active: false }) {
  const api = mockFetch({
    "GET /api/runs/2": run,
    "GET /api/runs/2/results": { ready: true, summary: null, requirements: [{ requirement_id: "FR-015" }, { requirement_id: "FR-016" }, { requirement_id: "FR-017" }] },
    "GET /api/runs/2/requirements/FR-016": d,
    ...extra,
  });
  vi.stubGlobal("fetch", api.fn);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={["/runs/2/requirements/FR-016"]}>
        <Routes>
          <Route path="/runs/:runId/requirements/:requirementId" element={<Requirement />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return api;
}

describe("Requirement page", () => {
  it("shows the verdict, flags, claims and the first component's code", async () => {
    setup(detail());
    expect(await screen.findByRole("heading", { name: "Check out a book" })).toBeInTheDocument();
    expect(screen.getByText("1 / 2 claims verified")).toBeInTheDocument();
    expect(screen.getByText("Requirement text looks incomplete.")).toBeInTheDocument();
    expect(screen.getByText("Claim 1 holds;", { exact: false })).toBeInTheDocument();     // incomplete marker stripped
    expect(screen.getByText("Not supported")).toBeInTheDocument();
    expect(screen.getByText("member.py:15")).toBeInTheDocument();                       // discarded evidence
    expect(screen.getByText("GENERATED DOCUMENTATION, NOT EVIDENCE")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Go to claim C1" })).toBeInTheDocument();
    expect(screen.getByText("Checked the call path by hand", { exact: false })).toBeInTheDocument();
  });

  it("a citation opens the cited component", async () => {
    setup(detail());
    await screen.findByText("member.py:17-20");
    fireEvent.click(screen.getByText("member.py:17-20"));
    expect(await screen.findByText("member 18")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Member.can_borrow/ })).toHaveAttribute("aria-selected", "true");
  });

  it("accept sends the verifier's verdict as a reviewer decision", async () => {
    const api = setup(detail(), { "POST /api/runs/2/requirements/FR-016/override": { verdict: {} } });
    fireEvent.click(await screen.findByRole("button", { name: "Accept verdict" }));
    await waitFor(() => {
      const call = api.calls.find((c) => c.method === "POST");
      expect(JSON.parse(call!.init!.body as string)).toEqual({ status: "partially_supported", note: "Accepted the verifier's verdict" });
    });
  });

  it("override needs a comment, then saves", async () => {
    const api = setup(detail(), { "POST /api/runs/2/requirements/FR-016/override": { verdict: {} } });
    fireEvent.click(await screen.findByRole("button", { name: "Override verdict" }));
    const save = screen.getByRole("button", { name: "Save override" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "not_supported_by_candidate" } });
    fireEvent.change(screen.getByPlaceholderText(/What did you check/), { target: { value: "No fine check exists anywhere." } });
    fireEvent.click(save);
    await waitFor(() => {
      const call = api.calls.find((c) => c.method === "POST");
      expect(JSON.parse(call!.init!.body as string)).toEqual({ status: "not_supported_by_candidate", note: "No fine check exists anywhere." });
    });
  });

  it("an accepted verdict can be withdrawn; an override can be removed", async () => {
    const api = setup(detail({ verdict: { status: "partially_supported", source: "human", machine: "partially_supported" } }),
      { "POST /api/runs/2/requirements/FR-016/override": { verdict: {} } });
    fireEvent.click(await screen.findByRole("button", { name: "✓ Accepted" }));
    await waitFor(() => expect(JSON.parse(api.calls.find((c) => c.method === "POST")!.init!.body as string).status).toBe("cleared"));
  });

  it("re-run verification posts this requirement; prev/next follow the results order", async () => {
    const api = setup(detail(), { "POST /api/runs/2/verify": { verifying: ["FR-016"] } });
    fireEvent.click(await screen.findByRole("button", { name: "Re-run verification" }));
    await waitFor(() => expect(JSON.parse(api.calls.find((c) => c.url === "/api/runs/2/verify")!.init!.body as string))
      .toEqual({ requirement_ids: ["FR-016"] }));
    expect(screen.getByRole("button", { name: "Previous requirement" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next requirement" })).toBeEnabled();
  });

  it("not found requirement", async () => {
    vi.stubGlobal("fetch", mockFetch({ "GET /api/runs/2": { ...makeRun(2, "completed"), stages: [], active: false } }).fn);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/runs/2/requirements/FR-999"]}>
          <Routes><Route path="/runs/:runId/requirements/:requirementId" element={<Requirement />} /></Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(await screen.findByText("Requirement not found.")).toBeInTheDocument();
  });
});
