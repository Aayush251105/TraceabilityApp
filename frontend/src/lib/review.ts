import type { DocBlock, ReviewCategory, ReviewItem } from "../api/types";

export const CATEGORIES: Record<ReviewCategory, { label: string; tab: string; c: string; b: string }> = {
  uncertain: { label: "Uncertain candidate", tab: "Uncertain candidates", c: "var(--ins)", b: "var(--ins-bg)" },
  flagged: { label: "Flagged for review", tab: "Flagged for review", c: "var(--rev)", b: "var(--rev-bg)" },
  incomplete: { label: "Possibly incomplete", tab: "Possibly incomplete", c: "var(--part)", b: "var(--part-bg)" },
  split: { label: "Possibly split or duplicate", tab: "Possibly split or duplicate", c: "var(--nf)", b: "var(--nf-bg)" },
};

export type Tab = ReviewCategory | "all";
export const TABS: Tab[] = ["uncertain", "flagged", "incomplete", "split", "all"];

/** Items in a tab: open ones first (in the server's order), then resolved ones. */
export function itemsFor(items: ReviewItem[], tab: Tab): ReviewItem[] {
  const inTab = tab === "all" ? items : items.filter((i) => i.category === tab);
  return [...inTab.filter((i) => !i.resolution), ...inTab.filter((i) => i.resolution)];
}

export function displayId(item: ReviewItem, idDraft?: string): string {
  if (idDraft) return idDraft;
  if (item.resolution_data?.requirement_id) return item.resolution_data.requirement_id;
  if (item.requirement_id) return item.requirement_id;
  const p = item.payload;
  if (p.kind === "candidate") return item.item_key.replace(/^cand:/, "");
  if (p.kind === "failure") return "Failed";
  return p.kind === "skipped_table" ? "Table" : "Section";
}

export interface ResolutionView {
  label: string;
  c: string;
  g: string;
}

export function resolutionView(item: ReviewItem): ResolutionView {
  const d = item.resolution_data ?? {};
  switch (item.resolution) {
    case "kept":
      return { label: d.requirement_id ? `Kept as ${d.requirement_id}` : "Kept", c: "var(--ok)", g: "✓" };
    case "edited":
      return { label: "Kept · text edited", c: "var(--ok)", g: "✓" };
    case "discarded":
      return { label: d.auto ? "Skipped automatically" : "Discarded", c: "var(--nf)", g: "–" };
    case "merged":
      return { label: `Merged into ${d.into ?? "?"}`, c: "var(--ins)", g: "→" };
    case "unreviewed":
      return { label: "Kept · unreviewed", c: "var(--part)", g: "!" };
    default:
      return { label: "Open", c: "var(--fg3)", g: "" };
  }
}

export function suggestionLabel(item: ReviewItem): string | null {
  const s = item.payload.suggestion;
  if (!s) return null;
  if (s.action === "merge" && s.target) return `Merge into ${s.target}`;
  if (s.action === "edit") return "Edit the text";
  if (s.action === "discard") return "Discard";
  return null;
}

/** "¶34–38 · 3.1 Catalog Management", "p.7", "Table 2 · row 4". */
export function locationLabel(loc: Record<string, number | string> | undefined): string {
  if (!loc) return "";
  const parts: string[] = [];
  if (loc.page != null) parts.push(loc.page_end && loc.page_end !== loc.page ? `p.${loc.page}–${loc.page_end}` : `p.${loc.page}`);
  if (loc.table != null) parts.push(`Table ${loc.table}${loc.row != null ? ` · row ${loc.row}` : ""}`);
  else if (loc.paragraph != null)
    parts.push(loc.paragraph_end && loc.paragraph_end !== loc.paragraph ? `¶${loc.paragraph}–${loc.paragraph_end}` : `¶${loc.paragraph}`);
  if (loc.section) parts.push(String(loc.section));
  return parts.join(" · ");
}

function normal(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

/**
 * Indexes of the document blocks an item came from: by paragraph range,
 * table, or page; when the location does not identify blocks, by its text.
 */
export function locateBlocks(blocks: DocBlock[], item: Pick<ReviewItem, "payload">): number[] {
  const loc = item.payload.location ?? {};
  const num = (v: unknown) => (typeof v === "number" ? v : v != null && v !== "" ? Number(v) : null);
  const para = num(loc.paragraph), paraEnd = num(loc.paragraph_end) ?? para;
  const table = num(loc.table), page = num(loc.page);
  let hits: number[] = [];
  if (table != null) {
    hits = blocks.flatMap((b, i) => (num(b.location.table) === table ? [i] : []));
  } else if (para != null) {
    hits = blocks.flatMap((b, i) => {
      const p = num(b.location.paragraph);
      return p != null && p >= para && p <= (paraEnd ?? para) ? [i] : [];
    });
  }
  const text = normal(item.payload.source_text || "");
  if (hits.length === 0 && text) {
    const head = text.slice(0, 60);
    hits = blocks.flatMap((b, i) => {
      const t = normal(b.kind === "table" ? b.rows.map((r) => r.join(" | ")).join(" ") : b.text);
      return t && (t.includes(head) || (t.length > 20 && head.includes(t.slice(0, 40)))) ? [i] : [];
    }).slice(0, 6);
  }
  if (hits.length === 0 && page != null) {
    hits = blocks.flatMap((b, i) => (num(b.location.page) === page ? [i] : [])).slice(0, 1);
  }
  // A skipped section: also the items under its heading (they would become requirements).
  for (const itemText of item.payload.items ?? []) {
    const t = normal(itemText).slice(0, 60);
    const at = blocks.findIndex((b, i) => !hits.includes(i) && normal(b.text).startsWith(t));
    if (at >= 0) hits.push(at);
  }
  return hits.sort((a, b) => a - b);
}
