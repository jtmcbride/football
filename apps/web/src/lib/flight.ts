import type { TrackingPlay } from "./types";

export interface FlightState {
  id: string; name: string; role: string | null;
  x: number; y: number; vx: number; vy: number;
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

export interface FlightReport {
  version: string; createdAt: string; fingerprint: string; splitRule: string;
  heldOutGames: string[]; developmentGames: string[];
  counts: Record<string, number>; skippedPlays: Record<string, number>;
  overall: FlightScores;
  byHorizon: (FlightScores & { seconds: number })[];
  byRole: (FlightScores & { role: string })[];
  limitations: string[];
}

/** Project the server's release-only velocity. Observations are used solely for error connectors. */
export function flightGhosts(play: TrackingPlay, frameIndex: number): Ghost[] {
  const forecast = play.flightForecast;
  const frame = play.frames[frameIndex];
  const arrival = play.play.passWindow?.arrivalFrameId;
  if (!forecast || forecast.reason || forecast.releaseFrameId === undefined || !frame ||
      frame.frameId < forecast.releaseFrameId || (arrival != null && frame.frameId > arrival)) return [];
  const seconds = (frame.frameId - forecast.releaseFrameId) / 10;
  return forecast.states.map((state) => {
    const x = state.x + state.vx * seconds;
    const y = state.y + state.vy * seconds;
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
