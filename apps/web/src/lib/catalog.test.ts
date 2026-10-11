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

  it("omits empty filters and the first page", () => {
    expect(buildPlaySearchUrl({ offense: " ", playType: "", text: "", page: 1 })).toBe("/api/plays");
  });
});
