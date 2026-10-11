export type EntityKind = "player" | "ball";

export interface TrackedEntity {
  id: string;
  kind: EntityKind;
  name: string;
  club: string;
  position: string | null;
  jersey: number | null;
  x: number;
  y: number;
  speed: number;
  acceleration: number;
  orientation: number | null;
  direction: number | null;
}

export interface TrackingFrame {
  frameId: number;
  timeMs: number;
  event: string | null;
  entities: TrackedEntity[];
}

export interface TrackingPlay {
  schemaVersion: number;
  source: {
    name: string;
    kind: "generated-demo" | "public-competition-data" | string;
    trackingFile: string | null;
  };
  field: {
    length: number;
    width: number;
    endZoneDepth: number;
  };
  play: {
    gameId: string;
    playId: string;
    title: string;
    description: string;
    offense: string | null;
    defense: string | null;
    quarter: number | null;
    down: number | null;
    yardsToGo: number | null;
    yardsGained: number | null;
    absoluteYardline: number | null;
    originalDirection: "left" | "right" | string;
    normalizedDirection: "right";
  };
  frames: TrackingFrame[];
}
