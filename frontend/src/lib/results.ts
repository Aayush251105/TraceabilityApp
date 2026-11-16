import type { ResultRow } from "../api/types";
import { VERDICT_ORDER, type Verdict } from "./status";

export type TypeFilter = "all" | "fr" | "nfr";
export type SortKey = "id" | "title" | "type" | "verdict" | "claims" | "links";

export function typeLabel(t: string): string {
  return t === "functional" ? "Functional" : t === "non-functional" ? "Non-functional" : t ? t[0].toUpperCase() + t.slice(1) : "—";
}

export function verdictCounts(rows: ResultRow[]): Record<Verdict, number> {
  const out = Object.fromEntries(VERDICT_ORDER.map((v) => [v, 0])) as Record<Verdict, number>;
  for (const r of rows) if (r.verdict.status in out) out[r.verdict.status as Verdict] += 1;
  return out;
}

export function supportedByType(rows: ResultRow[]) {
  const by = (pred: (r: ResultRow) => boolean) => {
    const sel = rows.filter(pred);
    return { supported: sel.filter((r) => r.verdict.status === "supported").length, total: sel.length };
  };
  return { functional: by((r) => r.type === "functional"), nonFunctional: by((r) => r.type !== "functional") };
}

export function filterRows(rows: ResultRow[], opts: { verdict: string | null; type: TypeFilter; q: string }): ResultRow[] {
  const q = opts.q.trim().toLowerCase();
  return rows.filter((r) =>
    (!opts.verdict || r.verdict.status === opts.verdict) &&
    (opts.type === "all" || (opts.type === "fr" ? r.type === "functional" : r.type !== "functional")) &&
    (!q || `${r.requirement_id} ${r.title}`.toLowerCase().includes(q)));
}

/** Sort rows; "id" keeps the document order (the server's order). */
export function sortRows(rows: ResultRow[], key: SortKey, dir: 1 | -1): ResultRow[] {
  const order = new Map(rows.map((r, i) => [r.requirement_id, i]));
  const k: Record<SortKey, (r: ResultRow) => number | string> = {
    id: (r) => order.get(r.requirement_id) ?? 0,
    title: (r) => r.title.toLowerCase(),
    type: (r) => r.type,
    verdict: (r) => {
      const i = VERDICT_ORDER.indexOf(r.verdict.status as Verdict);
      return i < 0 ? VERDICT_ORDER.length : i;
    },
    claims: (r) => (r.claims.total ? r.claims.supported / r.claims.total : -1),
    links: (r) => r.links.total,
  };
  return [...rows].sort((a, b) => {
    const x = k[key](a), y = k[key](b);
    return (x > y ? 1 : x < y ? -1 : 0) * dir || (order.get(a.requirement_id)! - order.get(b.requirement_id)!);
  });
}
