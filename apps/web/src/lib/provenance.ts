import type { CheckStatus, JoinStatus, PlayQualityStatus, QualityCheck, TrackingPlay } from "./types";

/** What the interface says about a play's tracking: its assessed status, or that none was recorded. */
export type QualityBadge = PlayQualityStatus | "unassessed";

export const QUALITY_LABELS: Record<QualityBadge, string> = {
  valid: "Valid",
  incomplete: "Incomplete",
  invalid: "Invalid",
  generated: "Generated",
  unassessed: "Not assessed",
};

export const QUALITY_EXPLANATIONS: Record<QualityBadge, string> = {
  valid: "Passed every tracking check. Fields the source lacks are listed below.",
  incomplete: "Usable, but part of the tracking is missing or suspect. Measurements may be unavailable.",
  invalid: "Failed a check that indicates corrupt data. Do not base analysis on this play.",
  generated: "Schematic data created for the demo. It is not NFL tracking.",
  unassessed: "This play was exported without a quality assessment. Re-export it from the catalog.",
};

export interface QualityCount {
  plays: number;
  valid: number;
  incomplete: number;
  invalid: number;
  validRate: number | null;
}

export interface QualityCoverage {
  version: number;
  assessedAt: string | null;
  overall: QualityCount;
  checks: Array<{ id: string } & Record<CheckStatus, number>>;
  seasons: Array<QualityCount & { season: number | null }>;
  weeks: Array<QualityCount & { season: number | null; week: number | null }>;
}

export function qualityBadge(play: TrackingPlay): QualityBadge {
  return play.provenance?.validation.status ?? "unassessed";
}

/** nflverse context is "unjoined" when the season file is loaded but lacks the play, or no file exists. */
export function isUnjoined(status: JoinStatus | null | undefined): boolean {
  return status === "unmatched" || status === "unavailable";
}

export type ContextBadge = "joined" | "conflicting" | "unjoined";

/** Null when the play is not part of a catalog (demo, import), where joining does not apply. */
export function contextBadge(play: TrackingPlay): ContextBadge | null {
  const status = play.provenance?.nflverse?.status ?? play.enrichment?.nflverse?.status;
  if (!status) return null;
  if (status === "conflicting") return "conflicting";
  return isUnjoined(status) ? "unjoined" : "joined";
}

const SEVERITY: Record<CheckStatus, number> = { error: 0, warning: 1, unavailable: 2, info: 3, pass: 4 };

/** Checks worth showing, most severe first; passing checks are only counted. */
export function findings(checks: QualityCheck[]): QualityCheck[] {
  return checks
    .filter((check) => check.status !== "pass")
    .sort((a, b) => SEVERITY[a.status] - SEVERITY[b.status]);
}

/** "9 of 12 checks passed" — never implies a clean play when checks were unavailable. */
export function checkSummary(checks: QualityCheck[]): string {
  const passed = checks.filter((check) => check.status === "pass").length;
  const unavailable = checks.filter((check) => check.status === "unavailable").length;
  const base = `${passed} of ${checks.length} checks passed`;
  return unavailable ? `${base} · ${unavailable} not evaluable` : base;
}

/** One-line statement of measured quality across the catalog. */
export function qualityCoverageSummary(coverage: QualityCoverage): string {
  const { overall } = coverage;
  if (overall.plays === 0) return "tracking quality not assessed";
  const parts = [`${overall.valid}/${overall.plays} plays valid`];
  if (overall.incomplete) parts.push(`${overall.incomplete} incomplete`);
  if (overall.invalid) parts.push(`${overall.invalid} invalid`);
  return parts.join(" · ");
}

export function describeRelease(provenance: NonNullable<TrackingPlay["provenance"]>): string | null {
  const { release } = provenance;
  if (!release) return null;
  const year = release.competitionYear ? ` · BDB ${release.competitionYear}` : "";
  const season = release.season ? ` · ${release.season} season` : "";
  return `${release.name}${year}${season}`;
}
