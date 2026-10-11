import { useEffect, useState } from "react";
import { fetchDataHealth, fetchPlayPage, fetchTrackingPlay } from "../lib/catalog";
import type { PlayPage, PlaySummary, PlayType } from "../lib/catalog";
import { JOIN_STATUS_LABELS, coverageSummary, formatEpa } from "../lib/enrichment";
import type { NflverseCoverage } from "../lib/enrichment";
import type { TrackingPlay } from "../lib/types";

const PAGE_SIZE = 8;
const PLAY_TYPES: Array<{ label: string; value: PlayType | "" }> = [
  { label: "All", value: "" },
  { label: "Pass", value: "pass" },
  { label: "Rush", value: "rush" },
  { label: "Other", value: "other" },
];

interface PlayBrowserProps {
  currentGameId: string;
  currentPlayId: string;
  onSelectPlay: (play: TrackingPlay) => void;
}

export function PlayBrowser({ currentGameId, currentPlayId, onSelectPlay }: PlayBrowserProps) {
  const [offense, setOffense] = useState("");
  const [searchText, setSearchText] = useState("");
  const [playType, setPlayType] = useState<PlayType | "">("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<PlayPage | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "offline">("loading");
  const [error, setError] = useState<string | null>(null);
  const [loadingPlayKey, setLoadingPlayKey] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<NflverseCoverage | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchDataHealth(controller.signal)
      .then((health) => setCoverage(health.nflverse))
      .catch(() => setCoverage(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setStatus("loading");
      setError(null);
      fetchPlayPage({ offense, playType, text: searchText, page, pageSize: PAGE_SIZE }, controller.signal)
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
  }, [offense, page, playType, searchText]);

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

  const updateFilter = (update: () => void) => {
    setPage(1);
    update();
  };

  const lastPage = result ? Math.max(1, Math.ceil(result.total / result.pageSize)) : 1;

  return (
    <section className="play-browser" id="play-browser" aria-labelledby="play-browser-title">
      <div className="browser-heading">
        <div>
          <p className="eyebrow">LOCAL CATALOG · CUT-UP QUEUE</p>
          <h2 id="play-browser-title">Find the next rep.</h2>
        </div>
        <p className={`browser-status ${status}`} role="status" aria-live="polite">
          <i />
          {status === "loading" ? "Scanning catalog" : status === "offline" ? "Catalog offline" : `${result?.total ?? 0} plays indexed`}
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
            value={offense}
            maxLength={3}
            placeholder="ANY"
            autoComplete="off"
            onChange={(event) => updateFilter(() => setOffense(event.target.value))}
          />
        </label>

        <fieldset className="type-filter">
          <legend>Play type</legend>
          <div className="type-tabs">
            {PLAY_TYPES.map((option) => (
              <button
                className={playType === option.value ? "active" : ""}
                type="button"
                key={option.label}
                aria-pressed={playType === option.value}
                onClick={() => updateFilter(() => setPlayType(option.value))}
              >
                {option.label}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="filter-field text-filter">
          <span>Description</span>
          <input
            value={searchText}
            placeholder="Search route, result, player…"
            type="search"
            onChange={(event) => updateFilter(() => setSearchText(event.target.value))}
          />
        </label>
      </div>

      {status === "offline" && !result ? (
        <div className="browser-message offline">
          <b>Catalog API is not running.</b>
          <span>Start it with <code>make api</code>. The loaded replay still works.</span>
          {error ? <small>{error}</small> : null}
        </div>
      ) : result?.items.length === 0 ? (
        <div className="browser-message">
          <b>No matching plays.</b>
          <span>Broaden the team, type, or description filters.</span>
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
