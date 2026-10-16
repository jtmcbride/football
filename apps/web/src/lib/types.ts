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
  /** Null when the source does not track speed for this frame (pass-window players after the throw). */
  speed: number | null;
  acceleration: number | null;
  orientation: number | null;
  direction: number | null;
  /** Source role; the play's route label applies only to the Targeted Receiver. */
  role?: string | null;
  playerToPredict?: boolean | null;
}

export interface TrackingFrame {
  frameId: number;
  timeMs: number;
  event: string | null;
  entities: TrackedEntity[];
}

export type JoinStatus = "matched" | "conflicting" | "unmatched" | "unavailable";

/** nflverse play-by-play context joined to a tracking play. Numeric fields are null when nflverse has no value. */
export interface NflverseFields {
  playType: string | null;
  quarter: number | null;
  clock: string | null;
  down: number | null;
  yardsToGo: number | null;
  offense: string | null;
  defense: string | null;
  offenseScore: number | null;
  defenseScore: number | null;
  epa: number | null;
  wpa: number | null;
  winProbability: number | null;
  yardsGained: number | null;
  airYards: number | null;
  yardsAfterCatch: number | null;
  isPenalty: boolean | null;
  penaltyType: string | null;
  penaltyYards: number | null;
  offenseFormation: string | null;
  offensePersonnel: string | null;
  defensePersonnel: string | null;
}

export interface NflverseEnrichment {
  status: JoinStatus;
  fingerprint: string | null;
  sourceFile: string | null;
  /** Fields the season's nflverse file does not contain at all (distinct from a null value). */
  unavailableFields: string[];
  fields: NflverseFields | null;
}

export type PlayQualityStatus = "valid" | "incomplete" | "invalid" | "generated";
export type CheckStatus = "pass" | "info" | "unavailable" | "warning" | "error";

export interface QualityCheck {
  id: string;
  label: string;
  status: CheckStatus;
  detail: string;
  count?: number;
}

/** Compact provenance served with every catalog play; absent from older exports. */
export interface Provenance {
  /** Null for a standalone extraction or generated play, which belong to no cataloged release. */
  release: {
    name: string;
    competitionYear: number | null;
    season: number | null;
    fingerprint: string;
    ingestedAt: string;
  } | null;
  files: string[];
  software: { name: string; version: string };
  direction: { original: string; normalized: string; method: string | null; rotated: boolean };
  fields: { available: string[]; missing: string[] };
  nflverse: { status: JoinStatus; fingerprint: string | null } | null;
  validation: {
    version: number;
    status: PlayQualityStatus;
    errors: number;
    warnings: number;
    checks: QualityCheck[];
  };
}

export interface TrackingPlay {
  flightForecast?: import("./flight").FlightForecast;
  accelerationForecast?: import("./flight").FlightForecast;
  schemaVersion: number;
  source: {
    name: string;
    kind: "generated-demo" | "public-competition-data" | string;
    trackingFile: string | null;
    trackingFormat?: "weekly" | "legacy-game" | "pass-window" | string;
    directionMethod?: "source" | "inferred-line-of-scrimmage" | "unavailable" | string;
    missingFields?: string[];
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
    normalizedDirection: "right" | "unknown";
    /** Where a pass-window release records the pass landing, normalized like the frames. */
    ballLanding?: { x: number; y: number } | null;
    passWindow?: {
      route: string | null;
      coverage: string | null;
      coverageType: string | null;
      formation: string | null;
      targetReceiverId: string | null;
      releaseFrameId: number;
      arrivalFrameId: number | null;
      eventSource: "derived-window-boundaries";
    };
  };
  frames: TrackingFrame[];
  enrichment?: { nflverse?: NflverseEnrichment };
  provenance?: Provenance;
}
