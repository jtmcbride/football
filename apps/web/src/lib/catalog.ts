import type { DataHealth } from "./enrichment";
import type { JoinStatus, TrackingPlay } from "./types";

export type PlayType = "pass" | "rush" | "other";

export interface PlaySearchFilters {
  offense?: string;
  playType?: PlayType | "";
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
  const text = filters.text?.trim();

  if (offense) params.set("offense", offense.toUpperCase());
  if (filters.playType) params.set("play_type", filters.playType);
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

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
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
