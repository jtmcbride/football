import { describe, expect, it } from "vitest";
import { buildRouteSearchUrl, fieldRoutePoints, observedRoute } from "./routes";
import type { TrackingPlay } from "./types";

function fixture(): TrackingPlay {
  return {
    schemaVersion: 1, source: { name: "test", kind: "test", trackingFile: null },
    field: { length: 120, width: 53.333, endZoneDepth: 10 },
    play: {
      gameId: "1", playId: "2", title: "A vs B", description: "", offense: "A", defense: "B",
      quarter: 1, down: 1, yardsToGo: 10, yardsGained: null, absoluteYardline: 30,
      originalDirection: "right", normalizedDirection: "right", ballLanding: { x: 50, y: 25 },
      passWindow: { route: "OUT", coverage: "ZONE_COVERAGE", coverageType: "COVER_3", formation: "SHOTGUN",
        targetReceiverId: "target", releaseFrameId: 3, arrivalFrameId: 4, eventSource: "derived-window-boundaries" },
    },
    frames: [1, 2, 3, 4].map((frameId) => ({
      frameId, timeMs: (frameId - 1) * 100, event: null,
      entities: [{ id: "target", kind: "player", name: "Receiver", club: "A", position: "WR", jersey: null,
        x: 30 + (frameId - 1) * 3, y: 10 + (frameId - 1) * 4,
        speed: null, acceleration: null, direction: null, orientation: null }],
    })),
  };
}

describe("observed receiver routes", () => {
  it("uses pre-throw positions, release-relative yards, and a separate landing point", () => {
    const play = fixture();
    const route = observedRoute(play)!;
    expect(route.points).toEqual([{ x: -6, y: -8 }, { x: -3, y: -4 }, { x: 0, y: 0 }]);
    expect(route.observedSeconds).toBe(0.2);
    expect(route.ballLanding).toEqual({ x: 14, y: 7 });
    expect(route.receiverName).toBe("Receiver");
    expect(play.frames[0].entities[0].x).toBe(30);
  });

  it("translates comparison paths to the reference release without mutating them", () => {
    const route = observedRoute(fixture())!;
    expect(fieldRoutePoints(route)).toBe("300.0,100.0 330.0,140.0 360.0,180.0");
    expect(fieldRoutePoints(route, { x: 50, y: 30 })).toBe("440.0,220.0 470.0,260.0 500.0,300.0");
    expect(route.release).toEqual({ x: 36, y: 18 });
  });

  it("does not connect missing receiver frames or invent a release or target", () => {
    const missing = fixture();
    missing.frames[1].entities = [];
    expect(observedRoute(missing)).toBeNull();
    const gap = fixture();
    gap.frames.splice(1, 1);
    expect(observedRoute(gap)).toBeNull();
    const unknown = fixture();
    unknown.play.normalizedDirection = "unknown";
    expect(observedRoute(unknown)).toBeNull();
    const legacy = fixture();
    delete legacy.play.passWindow;
    expect(observedRoute(legacy)).toBeNull();
    const noRelease = fixture();
    noRelease.frames = noRelease.frames.slice(0, 2);
    expect(observedRoute(noRelease)).toBeNull();
  });

  it("encodes filters and uses both play identifiers only in similarity mode", () => {
    const browse = new URL(buildRouteSearchUrl("OUT", "ZONE_COVERAGE", 2), "http://localhost");
    expect(Object.fromEntries(browse.searchParams)).toEqual({ page: "2", page_size: "6", route: "OUT", coverage: "ZONE_COVERAGE" });
    const similar = new URL(buildRouteSearchUrl("", "", 1, { gameId: "1", playId: "2" }), "http://localhost");
    expect(similar.searchParams.get("game_id")).toBe("1");
    expect(similar.searchParams.get("play_id")).toBe("2");
  });
});
