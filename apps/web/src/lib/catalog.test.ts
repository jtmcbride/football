import { describe, expect, it } from "vitest";
import { buildPlaySearchUrl } from "./catalog";

describe("buildPlaySearchUrl", () => {
  it("normalizes filters and encodes search text", () => {
    expect(buildPlaySearchUrl({
      offense: " ne ",
      playType: "pass",
      text: "third & long",
      page: 2,
      pageSize: 8,
    })).toBe("/api/plays?offense=NE&play_type=pass&text=third+%26+long&page=2&page_size=8");
  });

  it("serializes situation, team, EPA, and join filters, including zero values", () => {
    const url = new URL(buildPlaySearchUrl({
      season: 2017,
      week: 1,
      offense: "ne",
      defense: " kc ",
      down: 3,
      epaMin: 0,
      epaMax: -0.5,
      joinStatus: "unmatched",
    }), "http://localhost");
    expect(url.pathname).toBe("/api/plays");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      season: "2017",
      week: "1",
      offense: "NE",
      defense: "KC",
      down: "3",
      epa_min: "0",
      epa_max: "-0.5",
      join_status: "unmatched",
    });
  });

  it("omits empty filters and the first page", () => {
    expect(buildPlaySearchUrl({ offense: " ", playType: "", text: "", page: 1 })).toBe("/api/plays");
  });
});
