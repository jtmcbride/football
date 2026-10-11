import { useEffect, useState } from "react";
import { fetchDataHealth, fetchPlayPage, fetchTrackingPlay } from "../lib/catalog";
import type { PlayPage, PlaySummary, PlayType } from "../lib/catalog";
import { JOIN_STATUS_LABELS, coverageSummary, formatEpa } from "../lib/enrichment";
import type { NflverseCoverage } from "../lib/enrichment";
import {
  EMPTY_FILTERS,
  activeFilterCount,
  hasInvalidEpa,
  isInvalidNumber,
  seasonOptions,
  toSearchFilters,
  weekOptions,
} from "../lib/playFilters";
import type { BrowserFilters } from "../lib/playFilters";
import type { JoinStatus, TrackingPlay } from "../lib/types";

const PAGE_SIZE = 8;
const PLAY_TYPES: Array<{ label: string; value: PlayType | "" }> = [
  { label: "All", value: "" },
  { label: "Pass", value: "pass" },
  { label: "Rush", value: "rush" },
  { label: "Other", value: "other" },
];
const JOIN_STATUSES = Object.keys(JOIN_STATUS_LABELS) as JoinStatus[];

interface PlayBrowserProps {
  currentGameId: string;
  currentPlayId: string;
  onSelectPlay: (play: TrackingPlay) => void;
}

export function PlayBrowser({ currentGameId, currentPlayId, onSelectPlay }: PlayBrowserProps) {
  const [filters, setFilters] = useState<BrowserFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<PlayPage | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "offline">("loading");
  const [error, setError] = useState<string | null>(null);
  const [loadingPlayKey, setLoadingPlayKey] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<NflverseCoverage | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchDataHealth(controller.signal)
      .then((health) => setCoverage(health.nflverse ?? null))
      .catch(() => setCoverage(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setStatus("loading");
      setError(null);
      fetchPlayPage(toSearchFilters(filters, page, PAGE_SIZE), controller.signal)
        .then((nextResult) => {
          setResult(nextResult);
          setStatus("ready");
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setStatus("offline");
          setError(reason instanceof Error ? reason.message : "The play catalog is unavailable.");
        });
    }, 220);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [filters, page]);

  const choosePlay = async (summary: PlaySummary) => {
    const key = playKey(summary);
    setLoadingPlayKey(key);
    setError(null);
    try {
      onSelectPlay(await fetchTrackingPlay(summary.gameId, summary.playId));
      document.getElementById("replay")?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "That play could not be loaded.");
    } finally {
      setLoadingPlayKey(null);
    }
  };

  const updateFilters = (patch: Partial<BrowserFilters>) => {
    setPage(1);
    setFilters((current) => {
      const next = { ...current, ...patch };
      // A week that does not exist in the newly chosen season would silently return nothing.
      if (patch.season !== undefined && next.week !== "" && !weekOptions(coverage, next.season).includes(Number(next.week))) {
        next.week = "";
      }
      return next;
    });
  };

  const clearFilters = () => {
    setPage(1);
    setFilters(EMPTY_FILTERS);
  };

  const activeFilters = activeFilterCount(filters);
  const nflverseLoaded = coverage?.loaded !== false;
  const seasons = seasonOptions(coverage);
  const weeks = weekOptions(coverage, filters.season);
  const lastPage = result ? Math.max(1, Math.ceil(result.total / result.pageSize)) : 1;
  const total = result?.total ?? 0;

  return (
    <section className="play-browser" id="play-browser" aria-labelledby="play-browser-title">
      <div className="browser-heading">
        <div>
          <p className="eyebrow">LOCAL CATALOG · CUT-UP QUEUE</p>
          <h2 id="play-browser-title">Find the next rep.</h2>
        </div>
        <p className={`browser-status ${status}`} role="status" aria-live="polite">
          <i />
          {status === "loading"
            ? "Scanning catalog"
            : status === "offline"
              ? "Catalog offline"
              : activeFilters > 0
                ? `${total} matching plays`
                : `${total} plays indexed`}
        </p>
        {coverage ? (
          <p className={`browser-coverage ${coverage.loaded && coverage.overall.matched === coverage.overall.plays ? "complete" : "partial"}`}>
            {coverageSummary(coverage)}
          </p>
        ) : null}
      </div>

      <div className="browser-filters">
        <label className="filter-field team-filter">
          <span>Offense</span>
          <input
            value={filters.offense}
            maxLength={3}
            placeholder="ANY"
            autoComplete="off"
            onChange={(event) => updateFilters({ offense: event.target.value })}
          />
        </label>

        <label className="filter-field team-filter">
          <span>Defense</span>
          <input
            value={filters.defense}
            maxLength={3}
            placeholder="ANY"
            autoComplete="off"
            onChange={(event) => updateFilters({ defense: event.target.value })}
          />
        </label>

        <fieldset className="type-filter">
          <legend>Play type</legend>
          <div className="type-tabs">
            {PLAY_TYPES.map((option) => (
              <button
                className={filters.playType === option.value ? "active" : ""}
                type="button"
                key={option.label}
                aria-pressed={filters.playType === option.value}
                onClick={() => updateFilters({ playType: option.value })}
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="filter-field text-filter">
          <span>Description</span>
          <input
            value={filters.text}
            placeholder="Search route, result, player…"
            type="search"
            onChange={(event) => updateFilters({ text: event.target.value })}
          />
        </label>
      </div>

      <div className="browser-filters situation-filters">
        <label className="filter-field">
          <span>Season</span>
          <select
            value={filters.season}
            disabled={seasons.length === 0}
            onChange={(event) => updateFilters({ season: event.target.value })}
          >
            <option value="">Any</option>
            {seasons.map((season) => <option key={season} value={season}>{season}</option>)}
          </select>
        </label>

        <label className="filter-field">
          <span>Week</span>
          <select
            value={filters.week}
            disabled={weeks.length === 0}
            onChange={(event) => updateFilters({ week: event.target.value })}
          >
            <option value="">Any</option>
            {weeks.map((week) => <option key={week} value={week}>Week {week}</option>)}
          </select>
        </label>

        <label className="filter-field">
          <span>Down</span>
          <select value={filters.down} onChange={(event) => updateFilters({ down: event.target.value })}>
            <option value="">Any</option>
            {[1, 2, 3, 4].map((down) => <option key={down} value={down}>{down}</option>)}
          </select>
        </label>

        <label className="filter-field">
          <span>EPA min</span>
          <input
            value={filters.epaMin}
            inputMode="decimal"
            placeholder="−∞"
            autoComplete="off"
            disabled={!nflverseLoaded}
            aria-invalid={isInvalidNumber(filters.epaMin)}
            onChange={(event) => updateFilters({ epaMin: event.target.value })}
          />
        </label>

        <label className="filter-field">
          <span>EPA max</span>
          <input
            value={filters.epaMax}
            inputMode="decimal"
            placeholder="+∞"
            autoComplete="off"
            disabled={!nflverseLoaded}
            aria-invalid={isInvalidNumber(filters.epaMax)}
            onChange={(event) => updateFilters({ epaMax: event.target.value })}
          />
        </label>

        <label className="filter-field">
          <span>nflverse</span>
          <select
            value={filters.joinStatus}
            disabled={!nflverseLoaded}
            onChange={(event) => updateFilters({ joinStatus: event.target.value as JoinStatus | "" })}
          >
            <option value="">Any</option>
            {JOIN_STATUSES.map((value) => <option key={value} value={value}>{JOIN_STATUS_LABELS[value]}</option>)}
          </select>
        </label>

        <div className="filter-field filter-actions">
          <button type="button" disabled={activeFilters === 0} onClick={clearFilters}>
            Clear{activeFilters > 0 ? ` (${activeFilters})` : ""}
          </button>
        </div>
      </div>

      {!nflverseLoaded ? (
        <p className="browser-hint">EPA and nflverse filters need play-by-play data: run <code>football ingest nflverse</code>.</p>
      ) : hasInvalidEpa(filters) ? (
        <p className="browser-hint warn" role="alert">An EPA bound is not a number and is being ignored.</p>
      ) : filters.epaMin.trim() !== "" || filters.epaMax.trim() !== "" ? (
        <p className="browser-hint">EPA filters hide plays with no nflverse row.</p>
      ) : null}

      {status === "offline" && !result ? (
        <div className="browser-message offline">
          <b>Catalog API is not running.</b>
          <span>Start it with <code>make api</code>. The loaded replay still works.</span>
          {error ? <small>{error}</small> : null}
        </div>
      ) : result?.items.length === 0 ? (
        <div className="browser-message">
          <b>No matching plays.</b>
          <span>{activeFilters > 0 ? "No play satisfies all of the active filters." : "The catalog has no plays."}</span>
          {activeFilters > 0 ? <button className="browser-clear" type="button" onClick={clearFilters}>Clear filters</button> : null}
        </div>
      ) : (
        <div className={`play-results ${status === "loading" ? "refreshing" : ""}`} aria-busy={status === "loading"}>
          {result?.items.map((summary, index) => {
            const key = playKey(summary);
            const selected = summary.gameId === currentGameId && summary.playId === currentPlayId;
            return (
              <button
                className={`play-result ${selected ? "selected" : ""}`}
                type="button"
                key={key}
                disabled={loadingPlayKey !== null}
                aria-current={selected ? "true" : undefined}
                onClick={() => void choosePlay(summary)}
              >
                <span className="cut-number">{String((page - 1) * PAGE_SIZE + index + 1).padStart(2, "0")}</span>
                <span className="play-situation">
                  <b>{formatDown(summary.down, summary.yardsToGo)}</b>
                  <small>Q{summary.quarter ?? "—"} · W{summary.week ?? "—"}</small>
                </span>
                <span className="play-matchup">
                  <b>{summary.offense ?? "—"} <i>v</i> {summary.defense ?? "—"}</b>
                  <small>{summary.playType} · #{summary.playId}</small>
                </span>
                <span className="play-description">
                  {summary.description || "Description unavailable"}
                  <small className={`join-chip ${summary.joinStatus}`}>
                    {JOIN_STATUS_LABELS[summary.joinStatus]}
                    {summary.epa !== null ? ` · EPA ${formatEpa(summary.epa)}` : ""}
                  </small>
                </span>
                <span className={`play-gain ${(summary.yardsGained ?? 0) < 0 ? "loss" : ""}`}>
                  <b>{formatGain(summary.yardsGained)}</b>
                  <small>{loadingPlayKey === key ? "LOADING" : selected ? "ON FIELD" : "YARDS"}</small>
                </span>
              </button>
            );
          })}
        </div>
      )}

      {result && result.total > 0 ? (
        <div className="browser-pagination">
          <button type="button" disabled={page <= 1 || status === "loading"} onClick={() => setPage((value) => value - 1)}>← Previous</button>
          <span>Sheet {page} / {lastPage}</span>
          <button type="button" disabled={page >= lastPage || status === "loading"} onClick={() => setPage((value) => value + 1)}>Next →</button>
        </div>
      ) : null}

      {error && result ? <p className="browser-inline-error" role="alert">{error}</p> : null}
    </section>
  );
}

function playKey(summary: PlaySummary): string {
  return `${summary.gameId}-${summary.playId}`;
}

function formatDown(down: number | null, yards: number | null): string {
  if (down === null) return "Down —";
  const suffix = down === 1 ? "st" : down === 2 ? "nd" : down === 3 ? "rd" : "th";
  return `${down}${suffix} & ${yards ?? "goal"}`;
}

function formatGain(yards: number | null): string {
  if (yards === null) return "—";
  return `${yards > 0 ? "+" : ""}${yards}`;
}
