import type { TrackedEntity, TrackingFrame, TrackingPlay } from "./types";

export interface FrameMetrics {
  elapsedSeconds: number;
  nearestSeparation: number | null;
  formationWidth: number | null;
  ballSpeed: number | null;
  fastestPlayer: MeasuredEntity | null;
}

/** An entity whose speed was tracked in the frame. */
export type MeasuredEntity = TrackedEntity & { speed: number };

export type AnalysisEventKind = "snap" | "release" | "arrival" | "catch" | "tackle";

export interface AnalysisEvent {
  kind: AnalysisEventKind;
  label: string;
  frameIndex: number;
  frameId: number;
  elapsedSeconds: number;
}

export interface AnalysisPlayer {
  id: string;
  name: string;
  club: string;
  position: string | null;
  jersey: number | null;
}

export interface PlayerAnalysisSample {
  frameIndex: number;
  frameId: number;
  elapsedSeconds: number;
  speed: number | null;
  acceleration: number | null;
  routeDepth: number | null;
  lateralDisplacement: number | null;
  totalDisplacement: number | null;
  separation: number | null;
  opponent: AnalysisPlayer | null;
}

export interface PlayerAnalysis {
  player: AnalysisPlayer;
  window: {
    startIndex: number;
    endIndex: number;
    startEvent: AnalysisEventKind | null;
    endEvent: AnalysisEventKind | null;
    durationSeconds: number;
  };
  events: AnalysisEvent[];
  samples: PlayerAnalysisSample[];
  availability: {
    speed: boolean;
    acceleration: boolean;
    route: boolean;
    separation: boolean;
  };
  routeUnavailableReason: string | null;
  missingPlayerFrames: number;
}

const EVENT_KINDS: Readonly<Record<string, AnalysisEventKind>> = {
  ball_snap: "snap",
  snap_direct: "snap",
  pass_forward: "release",
  pass_shovel: "release",
  pass_arrived: "arrival",
  pass_arrival: "arrival",
  pass_outcome_caught: "catch",
  pass_caught: "catch",
  tackle: "tackle",
};

const EVENT_LABELS: Readonly<Record<AnalysisEventKind, string>> = {
  snap: "Snap",
  release: "Release",
  arrival: "Arrival",
  catch: "Catch",
  tackle: "Tackle",
};

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

  let fastestPlayer: MeasuredEntity | null = null;
  for (const entity of entities) {
    if (entity.kind !== "player" || entity.speed === null) continue;
    if (!fastestPlayer || entity.speed > fastestPlayer.speed) {
      fastestPlayer = { ...entity, speed: entity.speed };
    }
  }

  const snapIndex = findEventIndex(play.frames, "snap");
  const baseline = play.frames[snapIndex >= 0 ? snapIndex : 0];
  return {
    elapsedSeconds: frame && baseline ? (frame.timeMs - baseline.timeMs) / 1000 : 0,
    nearestSeparation,
    formationWidth,
    ballSpeed: ball?.speed ?? null,
    fastestPlayer,
  };
}

/** Builds a gap-preserving selected-player series for the disclosed analysis window. */
export function playerAnalysis(play: TrackingPlay, selectedEntityId: string): PlayerAnalysis | null {
  const entity = findPlayer(play.frames, selectedEntityId);
  if (!entity) return null;

  const snapIndex = findEventIndex(play.frames, "snap");
  const startIndex = snapIndex >= 0 ? snapIndex : 0;
  const tackleIndex = findEventIndex(play.frames, "tackle", startIndex);
  const endIndex = tackleIndex >= 0 ? tackleIndex : play.frames.length - 1;
  const startFrame = play.frames[startIndex];
  const endFrame = play.frames[endIndex];
  const snapEntity = snapIndex >= 0
    ? play.frames[snapIndex].entities.find((candidate) => candidate.id === selectedEntityId && candidate.kind === "player")
    : undefined;
  const routeAvailable = Boolean(snapEntity) && play.play.normalizedDirection === "right";
  const routeUnavailableReason = routeAvailable
    ? null
    : snapIndex < 0
      ? "Route displacement is unavailable because this play has no snap event."
      : !snapEntity
        ? "Route displacement is unavailable because the player is missing at the snap."
        : "Route displacement is unavailable because play direction could not be normalized.";
  const opposingClub = entity.club === play.play.offense
    ? play.play.defense
    : entity.club === play.play.defense
      ? play.play.offense
      : null;

  let missingPlayerFrames = 0;
  const samples: PlayerAnalysisSample[] = [];
  for (let frameIndex = startIndex; frameIndex <= endIndex; frameIndex += 1) {
    const frame = play.frames[frameIndex];
    const tracked = frame.entities.find((candidate) => candidate.id === selectedEntityId && candidate.kind === "player");
    if (!tracked) missingPlayerFrames += 1;
    const nearest = tracked && opposingClub ? nearestOpponent(frame, tracked, opposingClub) : null;
    const routeDepth = tracked && snapEntity && routeAvailable ? tracked.x - snapEntity.x : null;
    const lateralDisplacement = tracked && snapEntity && routeAvailable ? tracked.y - snapEntity.y : null;
    samples.push({
      frameIndex,
      frameId: frame.frameId,
      elapsedSeconds: (frame.timeMs - startFrame.timeMs) / 1000,
      speed: tracked?.speed ?? null,
      acceleration: tracked?.acceleration ?? null,
      routeDepth,
      lateralDisplacement,
      totalDisplacement: routeDepth === null || lateralDisplacement === null
        ? null
        : Math.hypot(routeDepth, lateralDisplacement),
      separation: nearest?.distance ?? null,
      opponent: nearest ? playerReference(nearest.player) : null,
    });
  }

  const events = play.frames.flatMap((frame, frameIndex) => {
    if (frameIndex < startIndex || frameIndex > endIndex || !frame.event) return [];
    const kind = analysisEventKind(frame.event);
    return kind ? [{
      kind,
      label: EVENT_LABELS[kind],
      frameIndex,
      frameId: frame.frameId,
      elapsedSeconds: (frame.timeMs - startFrame.timeMs) / 1000,
    }] : [];
  });

  return {
    player: playerReference(entity),
    window: {
      startIndex,
      endIndex,
      startEvent: snapIndex >= 0 ? "snap" : null,
      endEvent: tackleIndex >= 0 ? "tackle" : null,
      durationSeconds: Math.max(0, (endFrame.timeMs - startFrame.timeMs) / 1000),
    },
    events,
    samples,
    availability: {
      speed: samples.some((sample) => sample.speed !== null),
      acceleration: samples.some((sample) => sample.acceleration !== null),
      route: routeAvailable,
      separation: samples.some((sample) => sample.separation !== null),
    },
    routeUnavailableReason,
    missingPlayerFrames,
  };
}

/** Returns the source frame index closest to an elapsed chart time. */
export function nearestAnalysisFrame(samples: PlayerAnalysisSample[], elapsedSeconds: number): number {
  if (samples.length === 0) return 0;
  let nearest = samples[0];
  let nearestDistance = Math.abs(nearest.elapsedSeconds - elapsedSeconds);
  for (let index = 1; index < samples.length; index += 1) {
    const distance = Math.abs(samples[index].elapsedSeconds - elapsedSeconds);
    if (distance < nearestDistance) {
      nearest = samples[index];
      nearestDistance = distance;
    }
  }
  return nearest.frameIndex;
}

export function analysisEventKind(event: string): AnalysisEventKind | null {
  return EVENT_KINDS[event] ?? null;
}

export function eventLabel(event: string): string {
  return event.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function findEventIndex(frames: TrackingFrame[], kind: AnalysisEventKind, startIndex = 0): number {
  return frames.findIndex((frame, index) => index >= startIndex && frame.event !== null && analysisEventKind(frame.event) === kind);
}

function findPlayer(frames: TrackingFrame[], id: string): TrackedEntity | null {
  for (const frame of frames) {
    const entity = frame.entities.find((candidate) => candidate.id === id && candidate.kind === "player");
    if (entity) return entity;
  }
  return null;
}

function nearestOpponent(
  frame: TrackingFrame,
  selected: TrackedEntity,
  opposingClub: string,
): { player: TrackedEntity; distance: number } | null {
  let nearest: { player: TrackedEntity; distance: number } | null = null;
  for (const candidate of frame.entities) {
    if (candidate.kind !== "player" || candidate.club !== opposingClub) continue;
    const distance = Math.hypot(selected.x - candidate.x, selected.y - candidate.y);
    if (!nearest || distance < nearest.distance) nearest = { player: candidate, distance };
  }
  return nearest;
}

function playerReference(entity: TrackedEntity): AnalysisPlayer {
  return {
    id: entity.id,
    name: entity.name,
    club: entity.club,
    position: entity.position,
    jersey: entity.jersey,
  };
}
