import type { TrackingPlay } from "./types";

export type FlightBaseline = "constant-velocity" | "constant-acceleration";
export const BASELINE_LABELS: Record<FlightBaseline, string> = {
  "constant-velocity": "Constant velocity", "constant-acceleration": "Constant acceleration",
};

export interface FlightState {
  id: string; name: string; role: string | null;
  x: number; y: number; vx: number; vy: number;
  ax?: number; ay?: number;
}

export interface FlightForecast {
  version: string;
  reason: string | null;
  releaseFrameId?: number;
  releaseTimeMs?: number;
  states: FlightState[];
  unavailable: { id: string; name: string; reason: string }[];
}

export interface Ghost {
  state: FlightState;
  x: number; y: number;
  actual: { x: number; y: number } | null;
  error: number | null;
  offField: boolean;
}

export interface FlightScores {
  samples: number; missingSamples: number; endpoints: number;
  coordinateRmse: number | null; meanDistance: number | null; finalDistance: number | null;
}

export interface FlightScoreGroups {
  overall: FlightScores;
  byHorizon: (FlightScores & { seconds: number })[];
  byRole: (FlightScores & { role: string })[];
}

export interface FlightReport extends FlightScoreGroups {
  version: string; createdAt: string; fingerprint: string; splitRule: string;
  heldOutGames: string[]; developmentGames: string[];
  counts: Record<string, number>; skippedPlays: Record<string, number>;
  comparison: {
    counts: Record<string, number>; unavailableReasons: Record<string, number>;
    baselines: Record<FlightBaseline, FlightScoreGroups>;
    delta: Pick<FlightScores, "coordinateRmse" | "meanDistance" | "finalDistance">;
    gameResults: Record<string, number>;
  };
  limitations: string[];
}

export function forecastFor(play: TrackingPlay, baseline: FlightBaseline): FlightForecast | undefined {
  return baseline === "constant-acceleration" ? play.accelerationForecast : play.flightForecast;
}

/** Project the server's causal release state. Observations are used solely for error connectors. */
export function flightGhosts(play: TrackingPlay, frameIndex: number, baseline: FlightBaseline = "constant-velocity"): Ghost[] {
  const forecast = forecastFor(play, baseline);
  const frame = play.frames[frameIndex];
  const arrival = play.play.passWindow?.arrivalFrameId;
  if (!forecast || forecast.reason || forecast.releaseFrameId === undefined || !frame ||
      frame.frameId < forecast.releaseFrameId || (arrival != null && frame.frameId > arrival)) return [];
  const seconds = (frame.frameId - forecast.releaseFrameId) / 10;
  const states = forecast.states.filter((state) => baseline !== "constant-acceleration" ||
    (Number.isFinite(state.ax) && Number.isFinite(state.ay)));
  return states.map((state) => {
    const x = state.x + state.vx * seconds + 0.5 * (state.ax ?? 0) * seconds ** 2;
    const y = state.y + state.vy * seconds + 0.5 * (state.ay ?? 0) * seconds ** 2;
    const matches = frame.entities.filter((entity) => entity.id === state.id);
    const candidate = matches.length === 1 ? matches[0] : null;
    const actual = candidate && Number.isFinite(candidate.x) && Number.isFinite(candidate.y) ? candidate : null;
    return { state, x, y, actual, error: actual ? Math.hypot(x - actual.x, y - actual.y) : null,
      offField: x < 0 || x > play.field.length || y < 0 || y > play.field.width };
  });
}

export function yards(value: number | null | undefined): string {
  return value == null ? "Unavailable" : `${value.toFixed(2)} yd`;
}
