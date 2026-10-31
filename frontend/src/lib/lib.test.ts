import { describe, expect, it } from "vitest";

import { approx, clock, percent, plural, shortComponent } from "./format";
import { runMeta, stageMeta, verdictMeta, VERDICT_ORDER, VERDICTS } from "./status";

describe("format", () => {
  it("clock", () => {
    expect(clock(761)).toBe("12:41");
    expect(clock(3725)).toBe("1:02:05");
    expect(clock(-3)).toBe("00:00");
    expect(clock(null)).toBe("--:--");
  });

  it("approx remaining time", () => {
    expect(approx(1380)).toBe("~23 min");
    expect(approx(42)).toBe("~40 s");
    expect(approx(2)).toBe("~5 s");
    expect(approx(4200)).toBe("~1 h 10 min");
    expect(approx(7200)).toBe("~2 h");
    expect(approx(null)).toBe("—");
  });

  it("percent clamps", () => {
    expect(percent(0.444)).toBe("44%");
    expect(percent(1.2)).toBe("100%");
    expect(percent(undefined)).toBe("0%");
  });

  it("shortComponent and plural", () => {
    expect(shortComponent("library_system.models.loan.Loan.renew")).toBe("Loan.renew");
    expect(shortComponent("main")).toBe("main");
    expect(plural(1, "requirement")).toBe("1 requirement");
    expect(plural(3, "requirement")).toBe("3 requirements");
  });
});

describe("status", () => {
  it("every verdict has colour, shape and label", () => {
    expect(VERDICT_ORDER).toHaveLength(6);
    for (const v of VERDICT_ORDER) {
      const m = VERDICTS[v];
      expect(m.label).toBeTruthy();
      expect(m.c).toMatch(/^var\(--/);
      expect(m.b).toMatch(/^var\(--/);
    }
  });

  it("unknown values fall back safely", () => {
    expect(verdictMeta("pending").label).toBe("Pending");
    expect(verdictMeta(null).label).toBe("Pending");
    expect(stageMeta("bogus").label).toBe("Queued");
    expect(runMeta("paused").label).toBe("Paused for review");
    expect(runMeta("paused").r).toBe("2px"); // needs attention = square
  });
});
