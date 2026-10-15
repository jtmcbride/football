import type { DataHealth } from "./enrichment";
import type { QualityBadge } from "./provenance";
import type { JoinStatus, TrackingPlay } from "./types";

export type PlayType = "pass" | "rush" | "other";

export interface PlaySearchFilters {
  season?: number;
  week?: number;
  offense?: string;
  defense?: string;
  down?: number;
  playType?: PlayType | "";
  epaMin?: number;
  epaMax?: number;
  joinStatus?: JoinStatus | "";
  qualityStatus?: Exclude<QualityBadge, "generated"> | "";
  text?: string;
  page?: number;
  pageSize?: number;
}

export interface PlaySummary {
  gameId: string;
  playId: string;
  season: number | null;
  week: number | null;
  gameDate: string | null;
  offense: string | null;
  defense: string | null;
  quarter: number | null;
  down: number | null;
  yardsToGo: number | null;
  yardsGained: number | null;
  playType: PlayType;
  description: string;
  epa: number | null;
  joinStatus: JoinStatus;
  qualityStatus: QualityBadge;
}

export interface PlayPage {
  items: PlaySummary[];
  page: number;
  pageSize: number;
  total: number;
}

export function buildPlaySearchUrl(filters: PlaySearchFilters = {}): string {
  const params = new URLSearchParams();
  const offense = filters.offense?.trim();
  const defense = filters.defense?.trim();
  const text = filters.text?.trim();

  if (filters.season !== undefined) params.set("season", String(filters.season));
  if (filters.week !== undefined) params.set("week", String(filters.week));
  if (offense) params.set("offense", offense.toUpperCase());
  if (defense) params.set("defense", defense.toUpperCase());
  if (filters.down !== undefined) params.set("down", String(filters.down));
  if (filters.playType) params.set("play_type", filters.playType);
  if (filters.epaMin !== undefined) params.set("epa_min", String(filters.epaMin));
  if (filters.epaMax !== undefined) params.set("epa_max", String(filters.epaMax));
  if (filters.joinStatus) params.set("join_status", filters.joinStatus);
  if (filters.qualityStatus) params.set("quality_status", filters.qualityStatus);
  if (text) params.set("text", text);
  if (filters.page && filters.page > 1) params.set("page", String(filters.page));
  if (filters.pageSize) params.set("page_size", String(filters.pageSize));

  const query = params.toString();
  return query ? `/api/plays?${query}` : "/api/plays";
}

export async function fetchPlayPage(filters: PlaySearchFilters = {}, signal?: AbortSignal): Promise<PlayPage> {
  return fetchJson<PlayPage>(buildPlaySearchUrl(filters), signal);
}

export async function fetchDataHealth(signal?: AbortSignal): Promise<DataHealth> {
  return fetchJson<DataHealth>("/api/data-health", signal);
}

export async function fetchTrackingPlay(gameId: string, playId: string, signal?: AbortSignal): Promise<TrackingPlay> {
  return fetchJson<TrackingPlay>(`/api/plays/${encodeURIComponent(gameId)}/${encodeURIComponent(playId)}`, signal);
}

export async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (response.ok) return await response.json() as T;

  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.json() as { detail?: unknown };
    if (typeof body.detail === "string") detail = body.detail;
  } catch {
    // Keep the status fallback when the server did not return JSON.
  }
  throw new Error(detail);
}
