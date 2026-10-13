import { describe, expect, it } from "vitest";
import { eventLabel, frameMetrics, nearestAnalysisFrame, playerAnalysis } from "./metrics";
import type { TrackedEntity, TrackingFrame, TrackingPlay } from "./types";

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

describe("playerAnalysis", () => {
  it("measures route geometry and nearest opponents from snap through tackle", () => {
    const analysis = playerAnalysis(analysisPlay, "receiver");

    expect(analysis?.window).toMatchObject({
      startIndex: 1,
      endIndex: 6,
      startEvent: "snap",
      endEvent: "tackle",
      durationSeconds: 0.6,
    });
    expect(analysis?.events.map((event) => event.kind)).toEqual([
      "snap", "release", "arrival", "catch", "tackle",
    ]);
    expect(analysis?.samples[1]).toMatchObject({
      frameIndex: 2,
      elapsedSeconds: 0.1,
      speed: 6,
      routeDepth: 3,
      lateralDisplacement: 4,
      totalDisplacement: 5,
      separation: 3,
      opponent: { id: "corner-1", name: "Corner One" },
    });
    expect(analysis?.samples[3]).toMatchObject({
      routeDepth: 6,
      lateralDisplacement: 8,
      totalDisplacement: 10,
      separation: 1,
      opponent: { id: "corner-2", name: "Corner Two" },
    });
  });

  it("preserves missing frames as gaps and never treats absent acceleration as zero", () => {
    const analysis = playerAnalysis(analysisPlay, "receiver");
    const gap = analysis?.samples.find((sample) => sample.frameIndex === 3);

    expect(gap).toMatchObject({
      elapsedSeconds: 0.3,
      speed: null,
      routeDepth: null,
      separation: null,
    });
    expect(analysis?.missingPlayerFrames).toBe(1);
    expect(analysis?.availability.acceleration).toBe(false);
    expect(analysis?.samples.every((sample) => sample.acceleration === null)).toBe(true);
  });

  it("makes snap-relative route measurements unavailable without a usable snap baseline", () => {
    const noSnap = {
      ...analysisPlay,
      frames: analysisPlay.frames.map((frame) => ({
        ...frame,
        event: frame.event === "ball_snap" ? null : frame.event,
      })),
    };

    const analysis = playerAnalysis(noSnap, "receiver");

    expect(analysis?.window.startEvent).toBeNull();
    expect(analysis?.availability.route).toBe(false);
    expect(analysis?.routeUnavailableReason).toContain("snap");
    expect(analysis?.samples.every((sample) => sample.routeDepth === null)).toBe(true);
  });

  it("extends the analysis window to the final tracked frame when no tackle is present", () => {
    const noTackle = {
      ...analysisPlay,
      frames: analysisPlay.frames.map((frame) => ({
        ...frame,
        event: frame.event === "tackle" ? null : frame.event,
      })),
    };

    const analysis = playerAnalysis(noTackle, "receiver");

    expect(analysis?.window.endEvent).toBeNull();
    expect(analysis?.window.endIndex).toBe(7);
    expect(analysis?.window.durationSeconds).toBe(0.7);
  });

  it("finds the closest tracked frame across a cadence gap", () => {
    const samples = playerAnalysis(analysisPlay, "receiver")?.samples ?? [];

    expect(nearestAnalysisFrame(samples, 0.19)).toBe(2);
    expect(nearestAnalysisFrame(samples, 0.27)).toBe(3);
  });
});

describe("eventLabel", () => {
  it("humanizes tracking events", () => {
    expect(eventLabel("pass_forward")).toBe("Pass Forward");
  });
});

const analysisPlay: TrackingPlay = {
  ...play,
  frames: [
    analysisFrame(10, 0, null, player("receiver", "A", 8, 9, 2), [
      player("corner-1", "B", 12, 12, 1),
      player("corner-2", "B", 20, 20, 1),
    ]),
    analysisFrame(11, 100, "ball_snap", player("receiver", "A", 10, 10, 4), [
      player("corner-1", "B", 13, 14, 3),
      player("corner-2", "B", 20, 20, 2),
    ]),
    analysisFrame(12, 200, "pass_forward", player("receiver", "A", 13, 14, 6), [
      player("corner-1", "B", 13, 17, 4),
      player("corner-2", "B", 20, 20, 3),
    ]),
    analysisFrame(14, 400, "pass_arrived", null, [
      player("corner-1", "B", 15, 17, 4),
      player("corner-2", "B", 16, 18, 3),
    ]),
    analysisFrame(15, 500, "pass_outcome_caught", player("receiver", "A", 16, 18, 5), [
      player("corner-1", "B", 18, 18, 4),
      player("corner-2", "B", 17, 18, 3),
    ]),
    analysisFrame(16, 600, null, player("receiver", "A", 17, 18, 4), [
      player("corner-1", "B", 18, 18, 3),
      player("corner-2", "B", 19, 18, 2),
    ]),
    analysisFrame(17, 700, "tackle", player("receiver", "A", 18, 18, 0), [
      player("corner-1", "B", 18, 19, 1),
      player("corner-2", "B", 20, 18, 1),
    ]),
    analysisFrame(18, 800, null, player("receiver", "A", 18, 18, 0), []),
  ],
};

function analysisFrame(
  frameId: number,
  timeMs: number,
  event: string | null,
  selected: TrackedEntity | null,
  opponents: TrackedEntity[],
): TrackingFrame {
  return {
    frameId,
    timeMs,
    event,
    entities: selected ? [selected, ...opponents] : opponents,
  };
}

function player(id: string, club: string, x: number, y: number, speed: number): TrackedEntity {
  return {
    id,
    kind: "player",
    name: id === "receiver" ? "Selected Receiver" : id === "corner-1" ? "Corner One" : "Corner Two",
    club,
    position: club === "A" ? "WR" : "CB",
    jersey: club === "A" ? 80 : id === "corner-1" ? 21 : 22,
    x,
    y,
    speed,
    acceleration: null,
    orientation: null,
    direction: null,
  };
}
