import type { TrackedEntity, TrackingPlay } from "./types";

export interface FieldPoint {
  x: number;
  y: number;
}

export interface TeamShape {
  centroid: FieldPoint;
  /** Root-mean-square player distance from the centroid, in yards. */
  spread: number;
  width: number;
  depth: number;
  playerCount: number;
}

export interface QuarterbackShape extends FieldPoint {
  id: string;
  name: string;
  jersey: number | null;
  /** Positive values are behind the quarterback's normalized snap location. */
  depthFromSnap: number | null;
}

export interface ProtectionEnvelope {
  points: FieldPoint[];
  blockerCount: number;
  width: number;
  depth: number;
  area: number;
}

export interface TeamShapeSnapshot {
  frameIndex: number;
  frameId: number;
  offense: TeamShape | null;
  defense: TeamShape | null;
  centroidSeparation: number | null;
  quarterback: QuarterbackShape | null;
  quarterbackDepthUnavailableReason: "missing-snap" | "unknown-direction" | "missing-quarterback" | null;
  protection: ProtectionEnvelope | null;
  protectionUnavailableReason: "not-pass" | "missing-quarterback" | "insufficient-linemen" | "degenerate-geometry" | null;
}

const SNAP_EVENTS = new Set(["ball_snap", "snap_direct"]);
const LINE_POSITIONS = new Set(["C", "G", "T", "OG", "OT", "OL", "LG", "RG", "LT", "RT"]);

/** Precomputes current-frame team geometry once per play for replay and panel consumers. */
export function teamShapeSeries(play: TrackingPlay): TeamShapeSnapshot[] {
  const snapFrame = play.frames.find((frame) => frame.event !== null && SNAP_EVENTS.has(frame.event));
  const snapQuarterback = snapFrame?.entities.find(
    (entity) => entity.club === play.play.offense && isQuarterback(entity),
  ) ?? null;
  const playType = play.enrichment?.nflverse?.fields?.playType?.toLowerCase() ?? null;
  const pocketEligible = playType === null || playType === "pass" || playType === "sack";

  return play.frames.map((frame, frameIndex) => {
    const offensePlayers = teamPlayers(frame.entities, play.play.offense);
    const defensePlayers = teamPlayers(frame.entities, play.play.defense);
    const offense = measureTeam(offensePlayers);
    const defense = measureTeam(defensePlayers);
    const currentQuarterback = snapQuarterback
      ? offensePlayers.find((player) => player.id === snapQuarterback.id) ?? null
      : offensePlayers.find(isQuarterback) ?? null;
    const quarterback = currentQuarterback ? {
      id: currentQuarterback.id,
      name: currentQuarterback.name,
      jersey: currentQuarterback.jersey,
      x: currentQuarterback.x,
      y: currentQuarterback.y,
      depthFromSnap: snapQuarterback && play.play.normalizedDirection === "right"
        ? snapQuarterback.x - currentQuarterback.x
        : null,
    } : null;
    const quarterbackDepthUnavailableReason = !currentQuarterback
      ? "missing-quarterback"
      : !snapQuarterback
        ? "missing-snap"
        : play.play.normalizedDirection !== "right"
          ? "unknown-direction"
          : null;
    const blockers = offensePlayers.filter(isOffensiveLineman);
    const protection = pocketEligible && currentQuarterback
      ? protectionEnvelope(currentQuarterback, blockers)
      : null;
    const protectionUnavailableReason = protection
      ? null
      : !pocketEligible
        ? "not-pass"
        : !currentQuarterback
          ? "missing-quarterback"
          : blockers.length < 3
            ? "insufficient-linemen"
            : "degenerate-geometry";

    return {
      frameIndex,
      frameId: frame.frameId,
      offense,
      defense,
      centroidSeparation: offense && defense
        ? Math.hypot(offense.centroid.x - defense.centroid.x, offense.centroid.y - defense.centroid.y)
        : null,
      quarterback,
      quarterbackDepthUnavailableReason,
      protection,
      protectionUnavailableReason,
    };
  });
}

function teamPlayers(entities: TrackedEntity[], club: string | null): TrackedEntity[] {
  if (!club) return [];
  return entities.filter((entity) => entity.kind === "player" && entity.club === club);
}

function measureTeam(players: TrackedEntity[]): TeamShape | null {
  if (players.length === 0) return null;
  let sumX = 0;
  let sumY = 0;
  let minimumX = Number.POSITIVE_INFINITY;
  let maximumX = Number.NEGATIVE_INFINITY;
  let minimumY = Number.POSITIVE_INFINITY;
  let maximumY = Number.NEGATIVE_INFINITY;
  for (const player of players) {
    sumX += player.x;
    sumY += player.y;
    minimumX = Math.min(minimumX, player.x);
    maximumX = Math.max(maximumX, player.x);
    minimumY = Math.min(minimumY, player.y);
    maximumY = Math.max(maximumY, player.y);
  }
  const centroid = { x: sumX / players.length, y: sumY / players.length };
  let squaredDistance = 0;
  for (const player of players) {
    squaredDistance += (player.x - centroid.x) ** 2 + (player.y - centroid.y) ** 2;
  }
  return {
    centroid,
    spread: Math.sqrt(squaredDistance / players.length),
    width: maximumY - minimumY,
    depth: maximumX - minimumX,
    playerCount: players.length,
  };
}

function protectionEnvelope(quarterback: TrackedEntity, blockers: TrackedEntity[]): ProtectionEnvelope | null {
  if (blockers.length < 3) return null;
  const points = convexHull([quarterback, ...blockers].map(({ x, y }) => ({ x, y })));
  if (points.length < 3) return null;
  let minimumX = Number.POSITIVE_INFINITY;
  let maximumX = Number.NEGATIVE_INFINITY;
  let minimumY = Number.POSITIVE_INFINITY;
  let maximumY = Number.NEGATIVE_INFINITY;
  for (const point of points) {
    minimumX = Math.min(minimumX, point.x);
    maximumX = Math.max(maximumX, point.x);
    minimumY = Math.min(minimumY, point.y);
    maximumY = Math.max(maximumY, point.y);
  }
  return {
    points,
    blockerCount: blockers.length,
    width: maximumY - minimumY,
    depth: maximumX - minimumX,
    area: polygonArea(points),
  };
}

function convexHull(points: FieldPoint[]): FieldPoint[] {
  const sorted = [...points]
    .sort((left, right) => left.x - right.x || left.y - right.y)
    .filter((point, index, values) => index === 0 || point.x !== values[index - 1].x || point.y !== values[index - 1].y);
  if (sorted.length <= 2) return sorted;
  const lower: FieldPoint[] = [];
  for (const point of sorted) {
    while (lower.length >= 2 && cross(lower.at(-2)!, lower.at(-1)!, point) <= 0) lower.pop();
    lower.push(point);
  }
  const upper: FieldPoint[] = [];
  for (let index = sorted.length - 1; index >= 0; index -= 1) {
    const point = sorted[index];
    while (upper.length >= 2 && cross(upper.at(-2)!, upper.at(-1)!, point) <= 0) upper.pop();
    upper.push(point);
  }
  lower.pop();
  upper.pop();
  return [...lower, ...upper];
}

function cross(origin: FieldPoint, left: FieldPoint, right: FieldPoint): number {
  return (left.x - origin.x) * (right.y - origin.y) - (left.y - origin.y) * (right.x - origin.x);
}

function polygonArea(points: FieldPoint[]): number {
  let doubledArea = 0;
  for (let index = 0; index < points.length; index += 1) {
    const current = points[index];
    const next = points[(index + 1) % points.length];
    doubledArea += current.x * next.y - next.x * current.y;
  }
  return Math.abs(doubledArea) / 2;
}

function isQuarterback(entity: TrackedEntity): boolean {
  return entity.kind === "player" && entity.position?.toUpperCase() === "QB";
}

function isOffensiveLineman(entity: TrackedEntity): boolean {
  return entity.position !== null && LINE_POSITIONS.has(entity.position.toUpperCase());
}
