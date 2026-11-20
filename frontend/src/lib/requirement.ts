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

// ---------------------------------------------------------------------------
// Helper: what each linked component does and why it is linked (no LLM;
// built from the docstring, the mapping reason, the graph edges and the claims)
// ---------------------------------------------------------------------------

const DOC_SECTION = /^\s*(args|arguments|parameters|params|returns?|yields?|raises|exceptions|examples?|attributes|notes?|see also|todo)\s*:?\s*$/i;

/** First paragraph of a docstring, without Args/Returns/... sections, at most `max` characters. */
export function docSummary(content: string | null | undefined, max = 280): string {
  if (!content) return "";
  const lines = content.replace(/\r/g, "").trim().split("\n");
  const kept: string[] = [];
  for (const line of lines) {
    if (DOC_SECTION.test(line)) break;              // a Google/NumPy-style section starts
    if (/^\s*[-=]{3,}\s*$/.test(line)) break;       // NumPy underline
    if (!line.trim()) {
      if (kept.length) break;                       // end of the first paragraph
      continue;
    }
    kept.push(line.trim());
  }
  const text = kept.join(" ").replace(/\s+/g, " ").trim();
  if (text.length <= max) return text;
  const cut = text.slice(0, max);
  return `${cut.slice(0, Math.max(cut.lastIndexOf(" "), max - 20)).trimEnd()}…`;
}

/** The mapping agent's selection reason in plain words. */
export function plainReason(reason: string | null | undefined, rank: number | null): string {
  const r = (reason ?? "").trim();
  if (!r || /^rank 1$/i.test(r)) return rank != null && rank > 1 ? `Search match #${rank} for this requirement` : "Best search match for this requirement";
  let m = r.match(/^rank (\d+);\s*top-(\d+) in (\d+)\/(\d+)/i);
  if (m) return `Strong search match: #${m[1]} overall, in the top ${m[2]} of ${m[3]} of ${m[4]} search methods`;
  m = r.match(/^promoted: method of top-ranked class (.+)$/i);
  if (m) return `Method of ${shortComponent(m[1])}, the class that matched best`;
  m = r.match(/^class containing direct candidate (.+)$/i);
  if (m) return `Class that contains ${shortComponent(m[1])}`;
  return r.charAt(0).toUpperCase() + r.slice(1);
}

/** How a component relates to another linked component, seen from `self`. */
function edgePhrase(type: string, outgoing: boolean, other: string): string {
  const t = type.replace(/_/g, " ");
  const o = shortComponent(other);
  if (t === "calls" || t === "call reference") return outgoing ? `Calls ${o}` : `Called by ${o}`;
  if (t === "contains") return outgoing ? `Contains ${o}` : `Part of ${o}`;
  if (t === "instantiates") return outgoing ? `Creates ${o}` : `Created by ${o}`;
  if (t === "inherits") return outgoing ? `Subclass of ${o}` : `Base class of ${o}`;
  if (t === "imports") return outgoing ? `Uses ${o}` : `Used by ${o}`;
  return outgoing ? `${t} ${o}` : `${o} ${t} it`;
}

export interface HelperRow {
  component_id: string;
  name: string;
  role: "direct" | "supporting";
  where: string;
  what: { text: string; kind: string } | null;
  why: string[];
  claims: { n: number; meta: StatusMeta }[];
}

/** One row per linked component, direct ones first. */
export function helperRows(detail: RequirementDetail): HelperRow[] {
  const linked = new Set(detail.components.map((c) => c.component_id));
  const direct = new Set(detail.components.filter((c) => c.role === "direct").map((c) => c.component_id));
  const ordered = [...detail.components].sort((a, b) => (a.role === b.role ? 0 : a.role === "direct" ? -1 : 1));
  return ordered.map((c) => {
    const rel = detail.edges
      .filter((e) => e.from !== e.to && (e.from === c.component_id || e.to === c.component_id))
      .map((e) => {
        const outgoing = e.from === c.component_id;
        const other = outgoing ? e.to : e.from;
        return { other, text: edgePhrase(e.type, outgoing, other) };
      })
      .filter((x) => linked.has(x.other))
      .sort((a, b) => Number(direct.has(b.other)) - Number(direct.has(a.other)));   // relations to direct code first
    const rels = [...new Set(rel.map((x) => x.text))].slice(0, 3);
    const why = c.role === "direct"
      ? [plainReason(c.reason, c.rank), ...rels]
      : rels.length ? rels : [c.reason ? plainReason(c.reason, c.rank) : "Linked through the code graph"];
    const claims = detail.claims
      .map((cl, i) => ({ cl, i }))
      .filter(({ cl }) => cl.evidence.some((e) => e.component_id === c.component_id))
      .map(({ cl, i }) => ({ n: i + 1, meta: claimMeta(cl.verdict) }));
    const summary = docSummary(c.docstring?.content);
    return {
      component_id: c.component_id,
      name: c.name,
      role: c.role,
      where: `${fileName(c.path)}:${c.start_line}–${c.end_line}`,
      what: summary ? { text: summary, kind: c.docstring!.kind } : null,
      why,
      claims,
    };
  });
}

/** One sentence that orients a newcomer before the per-component rows. */
export function helperOverview(detail: RequirementDetail): string {
  const direct = detail.components.filter((c) => c.role === "direct").map((c) => c.name);
  const supporting = detail.components.length - direct.length;
  if (!direct.length) return "No code was mapped to this requirement.";
  const names = direct.length <= 3 ? direct.join(", ") : `${direct.slice(0, 3).join(", ")} and ${direct.length - 3} more`;
  const parts = [`Mainly implemented in ${names}`];
  if (supporting) parts.push(`${supporting} supporting component${supporting === 1 ? "" : "s"} give${supporting === 1 ? "s" : ""} context`);
  const verified = detail.claims.filter((c) => c.verdict === "supported").length;
  if (detail.claims.length) parts.push(`the verifier confirmed ${verified} of ${detail.claims.length} claim${detail.claims.length === 1 ? "" : "s"}`);
  return `${parts.join("; ")}.`;
}

export { shortComponent };
