import { describe, expect, it } from "vitest";
import { eventLabel, frameMetrics } from "./metrics";
import type { TrackingPlay } from "./types";

const play: TrackingPlay = {
  schemaVersion: 1,
  source: { name: "test", kind: "test", trackingFile: null },
  field: { length: 120, width: 53.3, endZoneDepth: 10 },
  play: {
    gameId: "1", playId: "2", title: "A vs B", description: "",
    offense: "A", defense: "B", quarter: 1, down: 1, yardsToGo: 10,
    yardsGained: null, absoluteYardline: 30, originalDirection: "right", normalizedDirection: "right",
  },
  frames: [{
    frameId: 1, timeMs: 0, event: "ball_snap",
    entities: [
      { id: "o1", kind: "player", name: "O", club: "A", position: "WR", jersey: 1, x: 30, y: 5, speed: 4, acceleration: 0, orientation: 90, direction: 90 },
      { id: "o2", kind: "player", name: "O2", club: "A", position: "WR", jersey: 2, x: 30, y: 45, speed: 6, acceleration: 0, orientation: 90, direction: 90 },
      { id: "d1", kind: "player", name: "D", club: "B", position: "CB", jersey: 3, x: 33, y: 9, speed: 5, acceleration: 0, orientation: 270, direction: 270 },
      { id: "ball", kind: "ball", name: "Football", club: "football", position: null, jersey: null, x: 30, y: 26, speed: 0, acceleration: 0, orientation: null, direction: null },
    ],
  }],
};

describe("frameMetrics", () => {
  it("measures separation and offensive width", () => {
    const result = frameMetrics(play, 0);
    expect(result.nearestSeparation).toBe(5);
    expect(result.formationWidth).toBe(40);
    expect(result.fastestPlayer?.name).toBe("O2");
  });
});

describe("eventLabel", () => {
  it("humanizes tracking events", () => {
    expect(eventLabel("pass_forward")).toBe("Pass Forward");
  });
});
