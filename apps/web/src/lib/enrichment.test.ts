import { describe, expect, it } from "vitest";
import { coverageSummary, formatEpa, formatPercent, formatScore, humanizeField } from "./enrichment";
import type { NflverseCoverage } from "./enrichment";

const count = { plays: 0, matched: 0, conflicting: 0, unmatched: 0, unavailable: 0, matchedRate: null };

describe("enrichment formatting", () => {
  it("signs EPA and shows unavailable values explicitly", () => {
    expect(formatEpa(1.4886)).toBe("+1.49");
    expect(formatEpa(-0.5131)).toBe("−0.51");
    expect(formatEpa(0)).toBe("0.00");
    expect(formatEpa(null)).toBe("—");
    expect(formatEpa(undefined)).toBe("—");
  });

  it("formats rates and scores without zero-filling", () => {
    expect(formatPercent(0.5)).toBe("50.0%");
    expect(formatPercent(null)).toBe("—");
    expect(formatScore(7, 3)).toBe("7–3");
    expect(formatScore(null, 3)).toBe("—");
  });

  it("turns API field ids into readable names", () => {
    expect(humanizeField("offenseFormation")).toBe("offense formation");
    expect(humanizeField("defendersInBox")).toBe("defenders in box");
    expect(humanizeField("epa")).toBe("epa");
  });

  it("states measured coverage and only mentions nonzero problem categories", () => {
    const loaded: NflverseCoverage = {
      loaded: true,
      overall: { ...count, plays: 177, matched: 177, matchedRate: 1 },
      seasons: [],
      weeks: [],
    };
    expect(coverageSummary(loaded)).toBe("177/177 matched to nflverse");

    const partial: NflverseCoverage = {
      ...loaded,
      overall: { ...count, plays: 10, matched: 6, conflicting: 1, unmatched: 2, unavailable: 1, matchedRate: 6 / 9 },
    };
    expect(coverageSummary(partial)).toBe(
      "6/10 matched to nflverse · 1 conflicting · 2 absent · 1 without a season file",
    );

    expect(coverageSummary({ loaded: false, overall: count, seasons: [], weeks: [] })).toBe("nflverse not loaded");
  });
});
