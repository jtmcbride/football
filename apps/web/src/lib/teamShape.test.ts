import { describe, expect, it } from "vitest";
import { teamShapeSeries } from "./teamShape";
import type { TrackedEntity, TrackingPlay } from "./types";

describe("teamShapeSeries", () => {
  it("measures centroids, RMS spread, quarterback depth, and the protection envelope", () => {
    const current = teamShapeSeries(shapePlay)[1];

    expect(current.offense).toMatchObject({
      centroid: { x: 10.25, y: 10 },
      width: 6,
      depth: 3,
      playerCount: 4,
    });
    expect(current.offense?.spread).toBeCloseTo(Math.sqrt(6.1875));
    expect(current.defense).toMatchObject({
      centroid: { x: 14, y: 10 },
      spread: 2,
      width: 4,
      depth: 0,
      playerCount: 2,
    });
    expect(current.centroidSeparation).toBe(3.75);
    expect(current.quarterback).toMatchObject({ id: "qb", depthFromSnap: 2 });
    expect(current.protection).toMatchObject({
      blockerCount: 3,
      width: 6,
      depth: 3,
      area: 9,
    });
    expect(current.protection?.points).toHaveLength(3);
  });

  it("keeps pocket and snap-relative depth unavailable when their required entities are absent", () => {
    const noSnapOrLine = {
      ...shapePlay,
      frames: shapePlay.frames.map((frame) => ({
        ...frame,
        event: null,
        entities: frame.entities.filter((entity) => entity.position === "QB" || entity.club === "B"),
      })),
    };

    const current = teamShapeSeries(noSnapOrLine)[1];

    expect(current.offense?.playerCount).toBe(1);
    expect(current.quarterback?.depthFromSnap).toBeNull();
    expect(current.quarterbackDepthUnavailableReason).toBe("missing-snap");
    expect(current.protection).toBeNull();
    expect(current.protectionUnavailableReason).toBe("insufficient-linemen");
  });

  it("does not assign a signed quarterback depth when play direction is unknown", () => {
    const unknownDirection = {
      ...shapePlay,
      play: { ...shapePlay.play, normalizedDirection: "unknown" as const },
    };

    const current = teamShapeSeries(unknownDirection)[1];

    expect(current.quarterback?.depthFromSnap).toBeNull();
    expect(current.quarterbackDepthUnavailableReason).toBe("unknown-direction");
    expect(current.protection).not.toBeNull();
  });
});

const shapePlay: TrackingPlay = {
  schemaVersion: 1,
  source: { name: "test", kind: "test", trackingFile: null },
  field: { length: 120, width: 53.3, endZoneDepth: 10 },
  play: {
    gameId: "1",
    playId: "shape",
    title: "A vs B",
    description: "",
    offense: "A",
    defense: "B",
    quarter: 1,
    down: 1,
    yardsToGo: 10,
    yardsGained: null,
    absoluteYardline: 12,
    originalDirection: "right",
    normalizedDirection: "right",
  },
  frames: [
    {
      frameId: 1,
      timeMs: 0,
      event: "ball_snap",
      entities: [
        entity("qb", "A", "QB", 10, 10),
        entity("c", "A", "C", 12, 10),
        entity("g", "A", "G", 12, 12),
        entity("t", "A", "T", 12, 8),
        entity("d1", "B", "DL", 14, 8),
        entity("d2", "B", "DL", 14, 12),
      ],
    },
    {
      frameId: 2,
      timeMs: 100,
      event: null,
      entities: [
        entity("qb", "A", "QB", 8, 10),
        entity("c", "A", "C", 11, 10),
        entity("g", "A", "G", 11, 13),
        entity("t", "A", "T", 11, 7),
        entity("d1", "B", "DL", 14, 8),
        entity("d2", "B", "DL", 14, 12),
      ],
    },
  ],
};

function entity(id: string, club: string, position: string, x: number, y: number): TrackedEntity {
  return {
    id,
    kind: "player",
    name: id.toUpperCase(),
    club,
    position,
    jersey: null,
    x,
    y,
    speed: 0,
    acceleration: null,
    orientation: null,
    direction: null,
  };
}
