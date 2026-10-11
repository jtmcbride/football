import type { TrackedEntity, TrackingFrame, TrackingPlay } from "./types";

export interface FrameMetrics {
  elapsedSeconds: number;
  nearestSeparation: number | null;
  formationWidth: number | null;
  ballSpeed: number | null;
  fastestPlayer: TrackedEntity | null;
}

export function frameMetrics(play: TrackingPlay, frameIndex: number): FrameMetrics {
  const frame = play.frames[frameIndex];
  const entities = frame?.entities ?? [];
  const offense = entities.filter((entity) => entity.kind === "player" && entity.club === play.play.offense);
  const defense = entities.filter((entity) => entity.kind === "player" && entity.club === play.play.defense);
  const ball = entities.find((entity) => entity.kind === "ball");

  let nearestSeparation: number | null = null;
  for (const offensivePlayer of offense) {
    for (const defender of defense) {
      const distance = Math.hypot(offensivePlayer.x - defender.x, offensivePlayer.y - defender.y);
      nearestSeparation = nearestSeparation === null ? distance : Math.min(nearestSeparation, distance);
    }
  }

  let formationWidth: number | null = null;
  if (offense.length > 1) {
    let minimum = Number.POSITIVE_INFINITY;
    let maximum = Number.NEGATIVE_INFINITY;
    for (const player of offense) {
      minimum = Math.min(minimum, player.y);
      maximum = Math.max(maximum, player.y);
    }
    formationWidth = maximum - minimum;
  }

  let fastestPlayer: TrackedEntity | null = null;
  for (const entity of entities) {
    if (entity.kind === "player" && (!fastestPlayer || entity.speed > fastestPlayer.speed)) {
      fastestPlayer = entity;
    }
  }

  const snapIndex = Math.max(0, play.frames.findIndex((candidate) => candidate.event === "ball_snap"));
  return {
    elapsedSeconds: (frameIndex - snapIndex) / 10,
    nearestSeparation,
    formationWidth,
    ballSpeed: ball?.speed ?? null,
    fastestPlayer,
  };
}

export function eventLabel(event: string): string {
  return event.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
