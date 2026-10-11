import type { JoinStatus } from "./types";

export interface JoinCount {
  plays: number;
  matched: number;
  conflicting: number;
  unmatched: number;
  unavailable: number;
  matchedRate: number | null;
}

export interface NflverseCoverage {
  loaded: boolean;
  overall: JoinCount;
  seasons: Array<JoinCount & { season: number | null; unavailableFields: string[] }>;
  weeks: Array<JoinCount & { season: number | null; week: number | null }>;
}

export interface DataHealth {
  ready: boolean;
  sourceName: string | null;
  counts: { games: number; plays: number; players: number; trackingFiles: number };
  warnings: string[];
  nflverse: NflverseCoverage;
}

export const JOIN_STATUS_LABELS: Record<JoinStatus, string> = {
  matched: "nflverse matched",
  conflicting: "nflverse conflict",
  unmatched: "not in nflverse",
  unavailable: "no nflverse season",
};

export function formatEpa(epa: number | null | undefined): string {
  if (epa === null || epa === undefined) return "—";
  const rounded = epa.toFixed(2);
  return `${epa > 0 ? "+" : epa < 0 ? "−" : ""}${rounded.replace("-", "")}`;
}

export function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

/** One-line statement of measured join coverage; never implies a join that was not measured. */
export function coverageSummary(coverage: NflverseCoverage): string {
  const { overall } = coverage;
  if (!coverage.loaded) return "nflverse not loaded";
  const parts = [`${overall.matched}/${overall.plays} matched to nflverse`];
  if (overall.conflicting) parts.push(`${overall.conflicting} conflicting`);
  if (overall.unmatched) parts.push(`${overall.unmatched} absent`);
  if (overall.unavailable) parts.push(`${overall.unavailable} without a season file`);
  return parts.join(" · ");
}

export function formatScore(offense: number | null, defense: number | null): string {
  return offense === null || defense === null ? "—" : `${offense}–${defense}`;
}

/** "offenseFormation" -> "offense formation" */
export function humanizeField(name: string): string {
  return name.replace(/([A-Z])/g, " $1").toLowerCase();
}
