import { describe, expect, it } from "vitest";
import { accelerationWeight, dampingRateFor, flightGhosts, yards, type FlightReport } from "./flight";
import type { TrackingPlay } from "./types";

function fixture(): TrackingPlay {
  return {
    schemaVersion: 1, source: { name: "test", kind: "test", trackingFile: null },
    field: { length: 120, width: 53.333, endZoneDepth: 10 },
    play: { gameId: "1", playId: "2", title: "test", description: "", offense: "A", defense: "B",
      quarter: null, down: null, yardsToGo: null, yardsGained: null, absoluteYardline: null,
      originalDirection: "right", normalizedDirection: "right",
      passWindow: { route: null, coverage: null, coverageType: null, formation: null,
        targetReceiverId: "2", releaseFrameId: 10, arrivalFrameId: 20, eventSource: "derived-window-boundaries" } },
    flightForecast: { version: "constant-velocity-v1", reason: null, releaseFrameId: 10, releaseTimeMs: 900,
      states: [{ id: "2", name: "Receiver", role: "Targeted Receiver", x: 30, y: 20, vx: 3, vy: 4 }], unavailable: [] },
    frames: [9, 10, 15, 20, 21].map((frameId) => ({ frameId, timeMs: (frameId - 1) * 100, event: null,
      entities: [{ id: "2", kind: "player", name: "Receiver", club: "A", position: "WR", jersey: null,
        x: 30, y: 20, speed: null, acceleration: null, orientation: null, direction: null }] })),
  };
}

describe("pass-flight ghosts", () => {
  it("uses elapsed source frames, not array index, and stays inside the analysis window", () => {
    const play = fixture();
    expect(flightGhosts(play, 0)).toEqual([]);
    expect(flightGhosts(play, 1)[0].error).toBe(0);
    expect(flightGhosts(play, 2)[0]).toMatchObject({ x: 31.5, y: 22, error: 2.5 });
    expect(flightGhosts(play, 3)[0]).toMatchObject({ x: 33, y: 24, error: 5 });
    expect(flightGhosts(play, 4)).toEqual([]);
  });

  it("does not feed future observations or landing back into predictions", () => {
    const play = fixture();
    const before = flightGhosts(play, 3)[0];
    play.frames[3].entities[0].x = 99;
    play.play.ballLanding = { x: 80, y: 50 };
    const after = flightGhosts(play, 3)[0];
    expect([after.x, after.y]).toEqual([before.x, before.y]);
    expect(after.error).not.toBe(before.error);
    expect(play.flightForecast!.states[0].x).toBe(30);
  });

  it("keeps ghosts across missing labels but makes their errors unavailable", () => {
    const play = fixture();
    play.frames[3].entities = [];
    expect(flightGhosts(play, 3)[0]).toMatchObject({ x: 33, y: 24, actual: null, error: null });
    play.frames[2].entities.push(play.frames[2].entities[0]);
    expect(flightGhosts(play, 2)[0].error).toBeNull();
    expect(yards(null)).toBe("Unavailable");
    expect(yards(0)).toBe("0.00 yd");
  });

  it("does not clamp off-field forecasts or invent a forecast for old exports", () => {
    const play = fixture();
    play.flightForecast!.states[0].vx = 100;
    expect(flightGhosts(play, 3)[0]).toMatchObject({ x: 130, offField: true });
    delete play.flightForecast;
    expect(flightGhosts(play, 3)).toEqual([]);
  });

  it("projects constant acceleration with the half-time-squared term and switches baselines", () => {
    const play = fixture();
    play.accelerationForecast = { ...play.flightForecast!, states: [
      { ...play.flightForecast!.states[0], ax: 2, ay: -4 },
    ] };
    expect(flightGhosts(play, 2, "constant-acceleration")[0]).toMatchObject({ x: 31.75, y: 21.5 });
    expect(flightGhosts(play, 3, "constant-acceleration")[0]).toMatchObject({ x: 34, y: 22 });
    expect(flightGhosts(play, 3, "constant-velocity")[0]).toMatchObject({ x: 33, y: 24 });
    play.frames[3].entities[0].x = 90;
    play.play.ballLanding = { x: 100, y: 10 };
    expect(flightGhosts(play, 3, "constant-acceleration")[0]).toMatchObject({ x: 34, y: 22 });
    expect(play.accelerationForecast.states[0].x).toBe(30);
  });

  it("keeps missing acceleration unavailable and never substitutes a velocity forecast", () => {
    const play = fixture();
    expect(flightGhosts(play, 3, "constant-acceleration")).toEqual([]);
    play.accelerationForecast = { ...play.flightForecast! };
    expect(flightGhosts(play, 3, "constant-acceleration")).toEqual([]);
    play.accelerationForecast = { ...play.flightForecast!, reason: "History missing" };
    expect(flightGhosts(play, 3, "constant-acceleration")).toEqual([]);
    expect(flightGhosts(play, 3, "constant-velocity")).toHaveLength(1);
  });

  it("integrates decaying acceleration with stable zero-rate and short-time limits", () => {
    expect(accelerationWeight(2, 1)).toBeCloseTo(1 + Math.exp(-2), 12);
    expect(accelerationWeight(2, 0)).toBe(2);
    expect(accelerationWeight(2, 1e-12)).toBeCloseTo(2, 10);
    expect(accelerationWeight(0, 2)).toBe(0);
    const play = fixture();
    play.accelerationForecast = { ...play.flightForecast!, states: [{ ...play.flightForecast!.states[0], ax: 2, ay: -4 }] };
    const ghost = flightGhosts(play, 3, "damped-acceleration", 1)[0];
    expect(ghost.x).toBeCloseTo(33 + 2 * Math.exp(-1), 12);
    expect(ghost.y).toBeCloseTo(24 - 4 * Math.exp(-1), 12);
    expect(flightGhosts(play, 3, "damped-acceleration", 0)[0]).toMatchObject({ x: 34, y: 22 });
    expect(flightGhosts(play, 3, "damped-acceleration")).toEqual([]);
    expect(flightGhosts(play, 3, "damped-acceleration", -1)).toEqual([]);
    play.frames[3].entities[0].x = 99;
    const after = flightGhosts(play, 3, "damped-acceleration", 1)[0];
    expect([after.x, after.y]).toEqual([ghost.x, ghost.y]);
    expect(after.error).not.toBe(ghost.error);
  });

  it("requires tuning provenance to match the current play before applying the rate", () => {
    const play = fixture();
    play.provenance = { release: { fingerprint: "fixture" } } as TrackingPlay["provenance"];
    const report = { version: "pass-flight-comparison-v3", fingerprint: "fixture",
      tuning: { fingerprint: "fixture", selectedRate: 2 } } as FlightReport;
    expect(dampingRateFor(play, report)).toBe(2);
    report.fingerprint = "another-source";
    expect(dampingRateFor(play, report)).toBeUndefined();
    report.fingerprint = "fixture";
    report.tuning.fingerprint = "another-source";
    expect(dampingRateFor(play, report)).toBeUndefined();
    report.tuning.fingerprint = "fixture";
    report.tuning.selectedRate = Number.NaN;
    expect(dampingRateFor(play, report)).toBeUndefined();
    expect(dampingRateFor(play, null)).toBeUndefined();
    const partial = { version: "pass-flight-comparison-v3", fingerprint: "fixture" } as FlightReport;
    expect(dampingRateFor(play, partial)).toBeUndefined();
    report.tuning.selectedRate = 0;
    expect(dampingRateFor(play, report)).toBe(0);
    report.version = "pass-flight-comparison-v2";
    expect(dampingRateFor(play, report)).toBeUndefined();
  });
});
