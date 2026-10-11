import { describe, expect, it } from "vitest";
import { clampFrame, isLinkedTo, parsePlayLink, withPlayLink, withoutPlayLink } from "./playLink";

describe("play links", () => {
  it("parses a complete link and defaults a missing frame to zero", () => {
    expect(parsePlayLink("?game=2017090700&play=68&frame=20")).toEqual({
      gameId: "2017090700",
      playId: "68",
      frameIndex: 20,
    });
    expect(parsePlayLink("?game=1&play=2")?.frameIndex).toBe(0);
  });

  it("rejects incomplete links and sanitizes bad frames", () => {
    expect(parsePlayLink("")).toBeNull();
    expect(parsePlayLink("?game=1")).toBeNull();
    expect(parsePlayLink("?game=1&play=2&frame=abc")?.frameIndex).toBe(0);
    expect(parsePlayLink("?game=1&play=2&frame=-5")?.frameIndex).toBe(0);
  });

  it("writes a link while preserving unrelated parameters", () => {
    const search = withPlayLink("?debug=1&game=old", { gameId: "9", playId: "4", frameIndex: 3 });
    const params = new URLSearchParams(search);
    expect(params.get("debug")).toBe("1");
    expect(params.get("game")).toBe("9");
    expect(params.get("play")).toBe("4");
    expect(params.get("frame")).toBe("3");
  });

  it("clears only the link parameters", () => {
    expect(withoutPlayLink("?debug=1&game=9&play=4&frame=3")).toBe("?debug=1");
    expect(withoutPlayLink("?game=9&play=4&frame=3")).toBe("");
  });

  it("matches the linked play regardless of frame", () => {
    expect(isLinkedTo("?game=9&play=4&frame=7", "9", "4")).toBe(true);
    expect(isLinkedTo("?game=9&play=4", "9", "5")).toBe(false);
    expect(isLinkedTo("", "9", "4")).toBe(false);
  });

  it("clamps frames to the play length", () => {
    expect(clampFrame(500, 74)).toBe(73);
    expect(clampFrame(-1, 74)).toBe(0);
    expect(clampFrame(Number.NaN, 74)).toBe(0);
  });
});
