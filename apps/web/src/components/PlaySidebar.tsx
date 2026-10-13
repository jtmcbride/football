import { useMemo } from "react";
import { JOIN_STATUS_LABELS, formatEpa, formatPercent, formatScore, humanizeField } from "../lib/enrichment";
import { frameMetrics } from "../lib/metrics";
import type { NflverseEnrichment, TrackingPlay } from "../lib/types";
import { ProvenanceCard } from "./ProvenanceCard";

interface PlaySidebarProps {
  play: TrackingPlay;
  frameIndex: number;
  selectedEntityId: string | null;
}

export function PlaySidebar({ play, frameIndex, selectedEntityId }: PlaySidebarProps) {
  const metrics = frameMetrics(play, frameIndex);
  const trackedEntity = play.frames[frameIndex].entities.find((candidate) => candidate.id === selectedEntityId);
  const selectedEntity = useMemo(() => {
    if (!selectedEntityId) return undefined;
    for (const frame of play.frames) {
      const candidate = frame.entities.find((item) => item.id === selectedEntityId);
      if (candidate) return candidate;
    }
    return undefined;
  }, [play.frames, selectedEntityId]);
  const entity = trackedEntity ?? selectedEntity;

  return (
    <aside className="sidebar">
      <section className="play-card">
        <div className="scorebug">
          <span>{play.play.offense ?? "OFF"}</span>
          <i>v</i>
          <span>{play.play.defense ?? "DEF"}</span>
        </div>
        <p className="eyebrow">PLAY CONTEXT</p>
        <h2>{formatDown(play.play.down, play.play.yardsToGo)}</h2>
        <p>{play.play.description}</p>
        <dl className="context-grid">
          <div><dt>Quarter</dt><dd>{play.play.quarter ?? "—"}</dd></div>
          <div><dt>Direction</dt><dd>{play.play.normalizedDirection === "right" ? "→ normalized" : "unavailable"}</dd></div>
          <div><dt>Game ID</dt><dd>{play.play.gameId}</dd></div>
          <div><dt>Play ID</dt><dd>{play.play.playId}</dd></div>
        </dl>
      </section>

      <ProvenanceCard play={play} />

      <NflverseCard enrichment={play.enrichment?.nflverse ?? null} />

      {entity ? (
        <section className="selected-card">
          <div className={`identity-dot ${entity.club === play.play.offense ? "offense" : "defense"}`}>
            {entity.jersey ?? entity.position}
          </div>
          <div>
            <p className="eyebrow">SELECTED PLAYER</p>
            <h3>{entity.name}</h3>
            <p>{entity.club} · {entity.position ?? "Position unavailable"}</p>
          </div>
          <dl className="selected-stats">
            <div><dt>Speed</dt><dd>{trackedEntity ? trackedEntity.speed.toFixed(1) : "Unavailable"} {trackedEntity ? <small>yd/s</small> : null}</dd></div>
            <div><dt>Accel.</dt><dd>{trackedEntity?.acceleration === null || !trackedEntity ? "Unavailable" : trackedEntity.acceleration.toFixed(1)} {trackedEntity?.acceleration === null || !trackedEntity ? null : <small>yd/s²</small>}</dd></div>
            <div><dt>Field x</dt><dd>{trackedEntity ? trackedEntity.x.toFixed(1) : "Unavailable"} {trackedEntity ? <small>yd</small> : null}</dd></div>
            <div><dt>Field y</dt><dd>{trackedEntity ? trackedEntity.y.toFixed(1) : "Unavailable"} {trackedEntity ? <small>yd</small> : null}</dd></div>
          </dl>
        </section>
      ) : (
        <section className="selected-card empty">
          <p className="eyebrow">PLAYER INSPECTOR</p>
          <p>Select any player marker to inspect speed, acceleration, and field position.</p>
        </section>
      )}

      <section className="metric-stack">
        <Metric label="TIME FROM SNAP" value={`${signed(metrics.elapsedSeconds)} s`} accent />
        <Metric label="TIGHTEST MATCHUP" value={formatYards(metrics.nearestSeparation)} />
        <Metric label="OFFENSIVE WIDTH" value={formatYards(metrics.formationWidth)} />
        <Metric
          label="FASTEST PLAYER"
          value={metrics.fastestPlayer ? `${metrics.fastestPlayer.position ?? metrics.fastestPlayer.name} · ${metrics.fastestPlayer.speed.toFixed(1)}` : "—"}
          suffix={metrics.fastestPlayer ? "yd/s" : undefined}
        />
      </section>
    </aside>
  );
}

function NflverseCard({ enrichment }: { enrichment: NflverseEnrichment | null }) {
  const fields = enrichment?.fields ?? null;
  const unavailable = enrichment?.unavailableFields ?? [];
  const situation = fields
    ? [fields.quarter === null ? null : `Q${fields.quarter}`, fields.clock].filter(Boolean).join(" ")
    : "";

  return (
    <section className={`nflverse-card ${enrichment?.status ?? "none"}`} aria-label="nflverse context">
      <p className="eyebrow">NFLVERSE CONTEXT</p>
      <p className="join-status"><i />{enrichment ? JOIN_STATUS_LABELS[enrichment.status] : "Not part of this source"}</p>
      {fields ? (
        <>
          {enrichment?.status === "conflicting" ? (
            <p className="nflverse-note">The nflverse row joined on game and play ID but disagrees on quarter or down. Treat these values with caution.</p>
          ) : null}
          <dl className="context-grid">
            <div><dt>EPA</dt><dd>{formatEpa(fields.epa)}</dd></div>
            <div><dt>WPA</dt><dd>{formatEpa(fields.wpa)}</dd></div>
            <div><dt>Win prob.</dt><dd>{formatPercent(fields.winProbability)}</dd></div>
            <div><dt>Clock</dt><dd>{situation || "—"}</dd></div>
            <div><dt>Score (O–D)</dt><dd>{formatScore(fields.offenseScore, fields.defenseScore)}</dd></div>
            <div><dt>Air yards</dt><dd>{fields.airYards ?? "—"}</dd></div>
            <div><dt>YAC</dt><dd>{fields.yardsAfterCatch ?? "—"}</dd></div>
            <div><dt>Penalty</dt><dd>{fields.isPenalty ? `${fields.penaltyType ?? "yes"}${fields.penaltyYards === null ? "" : ` · ${fields.penaltyYards}`}` : "none"}</dd></div>
          </dl>
        </>
      ) : enrichment ? (
        <p className="nflverse-note">
          {enrichment.status === "unmatched"
            ? "This season's nflverse file has no row for this play. Tracking is shown without play-by-play context."
            : "No nflverse file is loaded for this play's season. Run `football ingest nflverse` to add context."}
        </p>
      ) : null}
      {unavailable.length > 0 ? (
        <p className="nflverse-note">Not in this season's nflverse file: {unavailable.map(humanizeField).join(", ")}.</p>
      ) : null}
    </section>
  );
}

function Metric({ label, value, suffix, accent = false }: { label: string; value: string; suffix?: string; accent?: boolean }) {
  return (
    <div className={`metric ${accent ? "accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {suffix ? <small>{suffix}</small> : null}
    </div>
  );
}

function formatDown(down: number | null, yards: number | null): string {
  if (down === null) return "Down unavailable";
  if (down === 0) return "Special teams";
  const suffix = down === 1 ? "st" : down === 2 ? "nd" : down === 3 ? "rd" : "th";
  return `${down}${suffix} & ${yards ?? "goal"}`;
}

function formatYards(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)} yd`;
}

function signed(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
}
