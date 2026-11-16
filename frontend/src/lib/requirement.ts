/** Derived views for the requirement detail page (pure functions). */

import type { Claim, MappedComponent, RequirementDetail } from "../api/types";
import { shortComponent } from "./format";
import { verdictMeta, type StatusMeta } from "./status";

export const INCOMPLETE_PREFIX = /^\[requirement text looks incomplete[^\]]*\]\s*/;

/**
 * Claim verdicts use the verifier's per-claim vocabulary
 * (supported | not_supported | insufficient_evidence), not the requirement one.
 */
export function claimMeta(verdict: string | null | undefined): StatusMeta {
  if (verdict === "not_supported") return { ...verdictMeta("not_supported_by_candidate"), label: "Not supported" };
  return verdictMeta(verdict);
}

/** Split text on `backticks` into plain and code parts (the verifier quotes identifiers that way). */
export function codeSpans(text: string): { code: boolean; text: string }[] {
  return text.split(/(`[^`]+`)/g).filter(Boolean).map((t) =>
    t.length > 2 && t.startsWith("`") && t.endsWith("`") ? { code: true, text: t.slice(1, -1) } : { code: false, text: t });
}

export function fileName(path: string): string {
  return path.split("/").pop() || path;
}

export function citationLabel(path: string, a: number, b: number): string {
  return `${fileName(path)}:${a}${b !== a ? `-${b}` : ""}`;
}

/** Tag ("C2") → component id, from the citations the verifier made with those tags. */
export function tagMap(claims: Claim[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const c of claims) for (const e of c.evidence) if (e.tag) out[e.tag.toUpperCase()] = e.component_id;
  return out;
}

export function discardedLabel(ref: Claim["rejected"][number]["reference"], tags: Record<string, string>, comps: MappedComponent[]): string {
  if (!ref) return "citation";
  const tag = (ref.component ?? "").toUpperCase();
  const compId = tags[tag];
  const comp = comps.find((c) => c.component_id === compId);
  const where = comp ? fileName(comp.path) : tag || "?";
  const a = ref.start_line, b = ref.end_line;
  return a != null ? `${where}:${a}${b != null && b !== a ? `-${b}` : ""}` : where;
}

export interface LineMark {
  meta: StatusMeta;
  claim: number;
  mark?: string;
}

/**
 * Lines of one component cited by claims: the claim's verdict colour, and a
 * "C2" marker on the first line of each citation.  When two claims cite the
 * same line, the active claim wins, otherwise the first.
 */
export function lineMarks(claims: Claim[], componentId: string, activeClaim: number | null): Record<number, LineMark> {
  const out: Record<number, LineMark> = {};
  claims.forEach((c, ci) => {
    for (const e of c.evidence) {
      if (e.component_id !== componentId) continue;
      for (let n = e.start_line; n <= e.end_line; n++) {
        const prev = out[n];
        if (prev && !(ci === activeClaim && prev.claim !== activeClaim)) continue;   // first claim wins, unless this one is active
        out[n] = { meta: claimMeta(c.verdict), claim: ci, mark: n === e.start_line ? `C${ci + 1}` : undefined };
      }
    }
  });
  return out;
}

// ---------------------------------------------------------------------------
// Subgraph layout: requirement | direct | supporting, edges as curves
// ---------------------------------------------------------------------------

export const GRAPH_MIN_W = 640;
const ROW = 54;
const REQ_W = 150;
const NODE_W = 190;

export interface GraphNode {
  key: string;
  kind: "REQUIREMENT" | "DIRECT" | "SUPPORTING";
  label: string;
  x: number;
  y: number;
  w: number;
}

export interface GraphEdge {
  from: string;
  to: string;
  label: string;
  d: string;
  lx: number;
  ly: number;
}

/** Edge type as a short label (11px mono between columns). */
export function edgeLabel(type: string): string {
  const t = type.replace(/_/g, " ");
  return t === "call reference" ? "calls" : t;
}

/**
 * Three columns (requirement | direct | supporting) spread across the
 * available width, so the gaps that hold the edge labels grow with the panel.
 */
export function layoutGraph(detail: RequirementDetail, width = GRAPH_MIN_W): { nodes: GraphNode[]; edges: GraphEdge[]; height: number; width: number } {
  const W = Math.max(GRAPH_MIN_W, Math.floor(width));
  const req = detail.requirement;
  const direct = detail.components.filter((c) => c.role === "direct");
  const supporting = detail.components.filter((c) => c.role !== "direct");
  const rows = Math.max(direct.length, supporting.length, 1);
  const H = rows * ROW + 8;
  const gap = (W - REQ_W - 2 * NODE_W) / 2;
  const xDirect = REQ_W + gap, xSupport = W - NODE_W;
  const nodes: GraphNode[] = [
    { key: "req", kind: "REQUIREMENT", label: `${req.requirement_id} ${req.title}`, x: 0, y: H / 2 - 20, w: REQ_W },
    ...direct.map((c, i) => ({ key: c.component_id, kind: "DIRECT" as const, label: c.name, x: xDirect, y: H / 2 - direct.length * 27 + i * ROW + 7, w: NODE_W })),
    ...supporting.map((c, i) => ({ key: c.component_id, kind: "SUPPORTING" as const, label: c.name, x: xSupport, y: H / 2 - supporting.length * 27 + i * ROW + 7, w: NODE_W })),
  ];
  const pos = Object.fromEntries(nodes.map((n) => [n.key, n]));
  const list: [string, string, string][] = [
    ...direct.map((c) => ["req", c.component_id, "maps to"] as [string, string, string]),
    ...detail.edges.filter((e) => pos[e.from] && pos[e.to]).map((e) => [e.from, e.to, edgeLabel(e.type)] as [string, string, string]),
  ];
  const seen = new Set<string>();
  const edges: GraphEdge[] = [];
  for (const [a, b, label] of list) {
    const A = pos[a], B = pos[b];
    if (A.x === B.x) continue;                         // same column: not drawn (the design shows columns left to right)
    const key = `${a}>${b}>${label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    let x1 = A.x + A.w, x2 = B.x;
    if (A.x > B.x) { x1 = A.x; x2 = B.x + B.w; }
    const y1 = A.y + 20, y2 = B.y + 20, mx = (x1 + x2) / 2;
    edges.push({ from: a, to: b, label, d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, lx: mx, ly: (y1 + y2) / 2 });
  }
  // Crossing edges put their labels on the same spot: move later ones down until they are clear.
  const placed: { x: number; y: number }[] = [];
  for (const e of edges) {
    if (e.label === "maps to") continue;
    while (placed.some((p) => Math.abs(p.x - e.lx) < 60 && Math.abs(p.y - e.ly) < 13)) e.ly += 13;
    placed.push({ x: e.lx, y: e.ly });
  }
  return { nodes, edges, height: H, width: W };
}

// ---------------------------------------------------------------------------
// "Why these code locations"
// ---------------------------------------------------------------------------

export interface WhyRow {
  name: string;
  role: string;
  rank: string;
  keyword: string;
  semantic: string;
  because: string;
}

const score = (s?: { score: number }) => (s ? s.score.toFixed(s.score < 0.1 ? 3 : 2) : "—");

export function whyRows(detail: RequirementDetail): WhyRow[] {
  const byId = new Map(detail.search.map((s) => [s.component_id, s]));
  const mapped: WhyRow[] = detail.components.map((c) => {
    const ch = Object.keys(c.scores.channels).length ? c.scores.channels : byId.get(c.component_id)?.channels ?? {};
    const rank = c.rank ?? byId.get(c.component_id)?.rank ?? null;
    return {
      name: c.name,
      role: c.role === "direct" ? "Direct" : "Supporting",
      rank: rank != null ? `#${rank}` : "—",
      keyword: score(ch.component_lexical ?? ch.docstring_lexical),
      semantic: score(ch.component_vector ?? ch.docstring_vector),
      because: c.reason ?? (c.role === "direct" ? `Search rank #${rank ?? "?"}` : "Linked in the code graph"),
    };
  });
  const others: WhyRow[] = detail.search.filter((s) => !s.mapped).map((s) => ({
    name: s.name, role: "Not selected", rank: s.rank != null ? `#${s.rank}` : "—",
    keyword: score(s.channels.component_lexical ?? s.channels.docstring_lexical),
    semantic: score(s.channels.component_vector ?? s.channels.docstring_vector),
    because: "Search candidate below the mapping cut-off",
  }));
  return [...mapped, ...others];
}

export { shortComponent };
