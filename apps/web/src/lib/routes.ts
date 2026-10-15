import type { TrackingPlay } from "./types";

export interface RoutePath {
  gameId: string;
  playId: string;
  receiverId: string;
  receiverName: string;
  offense: string | null;
  defense: string | null;
  route: string | null;
  coverage: string | null;
  coverageType: string | null;
  observedSeconds: number;
  release: { x: number; y: number };
  /** Normalized field coordinates relative to the receiver at release, in yards. */
  points: Array<{ x: number; y: number }>;
  ballLanding: { x: number; y: number } | null;
  season?: number | null;
  week?: number | null;
  distanceYards?: number | null;
}

export interface RoutePage {
  supported: boolean;
  indexed: number;
  catalogPlays: number;
  routeOptions: string[];
  coverageOptions: string[];
  coverageTypeOptions: string[];
  items: RoutePath[];
  reference: RoutePath | null;
  total: number;
  page: number;
  pageSize: number;
}

export const routeKey = (route: { gameId: string; playId: string }) => `${route.gameId}/${route.playId}`;
export const routeLabel = (label: string | null | undefined) => label?.replaceAll("_", " ") ?? "Unavailable";
export const overlayDash = (index: number) => ["8 5", "3 5", "12 4 3 4"][index % 3];

/** Full observed pre-throw path, with the same eligibility rules as the search index. */
export function observedRoute(play: TrackingPlay): RoutePath | null {
  const window = play.play.passWindow;
  if (!window?.targetReceiverId || play.play.normalizedDirection !== "right") return null;
  const frames = play.frames.filter((frame) => frame.frameId <= window.releaseFrameId);
  if (frames.length < 2 || frames.at(-1)?.frameId !== window.releaseFrameId) return null;
  const positions = [];
  for (let index = 0; index < frames.length; index++) {
    const frame = frames[index];
    const targets = frame.entities.filter((entity) => entity.id === window.targetReceiverId);
    if (targets.length !== 1 || !Number.isFinite(targets[0].x) || !Number.isFinite(targets[0].y)) return null;
    if (index && (frame.frameId !== frames[index - 1].frameId + 1 || frame.timeMs - frames[index - 1].timeMs !== 100)) return null;
    positions.push(targets[0]);
  }
  const last = positions[positions.length - 1];
  const landing = play.play.ballLanding;
  return {
    gameId: play.play.gameId, playId: play.play.playId,
    receiverId: last.id, receiverName: last.name, offense: play.play.offense, defense: play.play.defense,
    route: window.route, coverage: window.coverage, coverageType: window.coverageType,
    observedSeconds: (frames[frames.length - 1].timeMs - frames[0].timeMs) / 1000,
    release: { x: last.x, y: last.y },
    points: positions.map((point) => ({ x: point.x - last.x, y: point.y - last.y })),
    ballLanding: landing ? { x: landing.x - last.x, y: landing.y - last.y } : null,
  };
}

export function fieldRoutePoints(route: RoutePath, anchor = route.release): string {
  return route.points.map((point) => `${((point.x + anchor.x) * 10).toFixed(1)},${((point.y + anchor.y) * 10).toFixed(1)}`).join(" ");
}

export function buildRouteSearchUrl(route: string, coverage: string, page: number, reference?: { gameId: string; playId: string }, coverageType = ""): string {
  const params = new URLSearchParams({ page: String(page), page_size: "6" });
  if (route) params.set("route", route);
  if (coverage) params.set("coverage", coverage);
  if (coverageType) params.set("coverage_type", coverageType);
  if (reference) {
    params.set("game_id", reference.gameId);
    params.set("play_id", reference.playId);
  }
  return `/api/routes?${params}`;
}
