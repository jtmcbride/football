import { describe, expect, it } from "vitest";
import type { NflverseCoverage } from "./enrichment";
import {
  EMPTY_FILTERS,
  activeFilterCount,
  hasInvalidEpa,
  seasonOptions,
  toSearchFilters,
  weekOptions,
} from "./playFilters";

const count = { plays: 1, matched: 1, conflicting: 0, unmatched: 0, unavailable: 0, matchedRate: 1 };
const coverage: NflverseCoverage = {
  loaded: true,
  overall: count,
  seasons: [
    { ...count, season: 2018, unavailableFields: [] },
    { ...count, season: 2017, unavailableFields: [] },
  ],
  weeks: [
    { ...count, season: 2017, week: 3 },
    { ...count, season: 2017, week: 1 },
    { ...count, season: 2018, week: 1 },
    { ...count, season: 2018, week: null },
  ],
};

describe("browser filters", () => {
  it("converts typed values and drops blanks and non-numbers", () => {
    const search = toSearchFilters(
      { ...EMPTY_FILTERS, season: "2017", week: "1", down: "3", epaMin: "-0.5", epaMax: "abc", joinStatus: "matched" },
      2,
      8,
    );
    expect(search).toMatchObject({ season: 2017, week: 1, down: 3, epaMin: -0.5, joinStatus: "matched", page: 2, pageSize: 8 });
    expect(search.epaMax).toBeUndefined();
    expect(toSearchFilters(EMPTY_FILTERS, 1, 8).season).toBeUndefined();
  });

  it("accepts a typographic minus and rejects fractional integers", () => {
    expect(toSearchFilters({ ...EMPTY_FILTERS, epaMin: "−1.25" }, 1, 8).epaMin).toBe(-1.25);
    expect(toSearchFilters({ ...EMPTY_FILTERS, week: "1.5" }, 1, 8).week).toBeUndefined();
  });

  it("counts only filters that narrow the results", () => {
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0);
    expect(activeFilterCount({ ...EMPTY_FILTERS, offense: "  ", epaMax: "x" })).toBe(0);
    expect(activeFilterCount({ ...EMPTY_FILTERS, offense: "NE", down: "3", epaMin: "0", joinStatus: "unmatched" })).toBe(4);
  });

  it("flags an EPA bound that is being ignored", () => {
    expect(hasInvalidEpa({ ...EMPTY_FILTERS, epaMin: "-" })).toBe(true);
    expect(hasInvalidEpa({ ...EMPTY_FILTERS, epaMin: "-1", epaMax: "2" })).toBe(false);
    expect(hasInvalidEpa(EMPTY_FILTERS)).toBe(false);
  });

  it("derives sorted season and week options from catalog coverage", () => {
    expect(seasonOptions(coverage)).toEqual([2017, 2018]);
    expect(weekOptions(coverage, "")).toEqual([1, 3]);
    expect(weekOptions(coverage, "2017")).toEqual([1, 3]);
    expect(weekOptions(coverage, "2018")).toEqual([1]);
    expect(seasonOptions(null)).toEqual([]);
    expect(weekOptions(null, "")).toEqual([]);
  });
});
