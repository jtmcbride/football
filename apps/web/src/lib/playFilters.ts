import type { PlaySearchFilters, PlayType } from "./catalog";
import type { NflverseCoverage } from "./enrichment";
import type { JoinStatus } from "./types";

/** Filter state exactly as typed or selected; converted to a query by `toSearchFilters`. */
export interface BrowserFilters {
  offense: string;
  defense: string;
  playType: PlayType | "";
  text: string;
  season: string;
  week: string;
  down: string;
  epaMin: string;
  epaMax: string;
  joinStatus: JoinStatus | "";
}

export const EMPTY_FILTERS: BrowserFilters = {
  offense: "",
  defense: "",
  playType: "",
  text: "",
  season: "",
  week: "",
  down: "",
  epaMin: "",
  epaMax: "",
  joinStatus: "",
};

export function toSearchFilters(filters: BrowserFilters, page: number, pageSize: number): PlaySearchFilters {
  return {
    offense: filters.offense,
    defense: filters.defense,
    playType: filters.playType,
    text: filters.text,
    season: parseInteger(filters.season),
    week: parseInteger(filters.week),
    down: parseInteger(filters.down),
    epaMin: parseNumber(filters.epaMin),
    epaMax: parseNumber(filters.epaMax),
    joinStatus: filters.joinStatus,
    page,
    pageSize,
  };
}

/** Number of filters that currently narrow the results. */
export function activeFilterCount(filters: BrowserFilters): number {
  const search = toSearchFilters(filters, 1, 1);
  return [
    search.offense?.trim(),
    search.defense?.trim(),
    search.playType,
    search.text?.trim(),
    search.season,
    search.week,
    search.down,
    search.epaMin,
    search.epaMax,
    search.joinStatus,
  ].filter((value) => value !== undefined && value !== "").length;
}

/** True when a typed EPA bound is present but not a number, so it is being ignored. */
export function hasInvalidEpa(filters: BrowserFilters): boolean {
  return isInvalidNumber(filters.epaMin) || isInvalidNumber(filters.epaMax);
}

/** Non-empty text that does not parse as a number. */
export function isInvalidNumber(value: string): boolean {
  return value.trim() !== "" && parseNumber(value) === undefined;
}

export function seasonOptions(coverage: NflverseCoverage | null): number[] {
  return unique((coverage?.seasons ?? []).map((item) => item.season));
}

/** Weeks present in the catalog, limited to the selected season when there is one. */
export function weekOptions(coverage: NflverseCoverage | null, season: string): number[] {
  const selected = parseInteger(season);
  return unique(
    (coverage?.weeks ?? [])
      .filter((item) => selected === undefined || item.season === selected)
      .map((item) => item.week),
  );
}

function unique(values: Array<number | null>): number[] {
  return [...new Set(values.filter((value): value is number => value !== null))].sort((a, b) => a - b);
}

function parseInteger(value: string): number | undefined {
  const parsed = parseNumber(value);
  return parsed !== undefined && Number.isInteger(parsed) ? parsed : undefined;
}

function parseNumber(value: string): number | undefined {
  const trimmed = value.trim();
  if (trimmed === "") return undefined;
  const parsed = Number(trimmed.replace("−", "-"));
  return Number.isFinite(parsed) ? parsed : undefined;
}
