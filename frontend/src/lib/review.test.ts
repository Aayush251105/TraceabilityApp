import { describe, expect, it } from "vitest";

import type { DocBlock } from "../api/types";
import { item } from "../test/fixtures";
import { displayId, itemsFor, locateBlocks, locationLabel, resolutionView, suggestionLabel } from "./review";


const block = (text: string, location: Record<string, number>, kind: DocBlock["kind"] = "paragraph"): DocBlock =>
  ({ kind, text, level: 1, rows: [], location });

describe("review helpers", () => {
  it("open items first within a tab", () => {
    const items = [item("a", { resolution: "kept" }), item("b"), item("c", { category: "split" }), item("d", { resolution: "discarded" })];
    expect(itemsFor(items, "all").map((i) => i.item_key)).toEqual(["b", "c", "a", "d"]);
    expect(itemsFor(items, "flagged").map((i) => i.item_key)).toEqual(["b", "a", "d"]);
  });

  it("display IDs", () => {
    expect(displayId(item("req:3", { requirement_id: "FR-003" }))).toBe("FR-003");
    expect(displayId(item("req:3", { requirement_id: "FR-003" }), "FR-030")).toBe("FR-030");
    expect(displayId(item("cand:C-0005", {}, { kind: "candidate" }))).toBe("C-0005");
    expect(displayId(item("skip:table:1", {}, { kind: "skipped_table" }))).toBe("Table");
  });

  it("resolution labels", () => {
    expect(resolutionView(item("a", { resolution: "merged", resolution_data: { into: "FR-034" } })).label).toBe("Merged into FR-034");
    expect(resolutionView(item("a", { resolution: "discarded", resolution_data: { auto: true } })).label).toBe("Skipped automatically");
    expect(resolutionView(item("a", { resolution: "kept", resolution_data: { requirement_id: "FR-050" } })).label).toBe("Kept as FR-050");
    expect(resolutionView(item("a", { resolution: "unreviewed" })).label).toBe("Kept · unreviewed");
  });

  it("suggestions and locations", () => {
    expect(suggestionLabel(item("a", {}, { suggestion: { action: "merge", target: "FR-021" } }))).toBe("Merge into FR-021");
    expect(suggestionLabel(item("a"))).toBeNull();
    expect(locationLabel({ paragraph: 34, paragraph_end: 38, section: "3.1 Catalog" })).toBe("¶34–38 · 3.1 Catalog");
    expect(locationLabel({ page: 7, table: 2, row: 4 })).toBe("p.7 · Table 2 · row 4");
  });

  it("locates source blocks by paragraph range, table, text, and section items", () => {
    const blocks = [
      block("3.4 Lending", { paragraph: 30 }, "heading"),
      block("FR-021 The system shall reject the checkout when:", { paragraph: 31 }),
      block("the member has 5 or more active loans;", { paragraph: 32 }, "list_item"),
      block("Glossary", { table: 2 }, "table"),
      block("Librarians usually work at the desk.", { page: 9 }),
    ];
    expect(locateBlocks(blocks, item("a", {}, { location: { paragraph: 31, paragraph_end: 32 } }))).toEqual([1, 2]);
    expect(locateBlocks(blocks, item("a", {}, { location: { table: 2 } }))).toEqual([3]);
    expect(locateBlocks(blocks, item("a", {}, { source_text: "Librarians  usually work at the desk." }))).toEqual([4]);
    expect(locateBlocks(blocks, item("a", {}, { location: { paragraph: 30 }, items: ["The member has 5 or more active loans;"] }))).toEqual([0, 2]);
    expect(locateBlocks(blocks, item("a", {}, { location: { paragraph: 99 } }))).toEqual([]);
  });
});
