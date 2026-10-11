import { frameMetrics } from "../lib/metrics";
import type { TrackingPlay } from "../lib/types";

interface PlaySidebarProps {
  play: TrackingPlay;
  frameIndex: number;
  selectedEntityId: string | null;
}

export function PlaySidebar({ play, frameIndex, selectedEntityId }: PlaySidebarProps) {
  const metrics = frameMetrics(play, frameIndex);
  const entity = play.frames[frameIndex].entities.find((candidate) => candidate.id === selectedEntityId);

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
            <div><dt>Speed</dt><dd>{entity.speed.toFixed(1)} <small>yd/s</small></dd></div>
            <div><dt>Accel.</dt><dd>{entity.acceleration === null ? "—" : entity.acceleration.toFixed(1)} {entity.acceleration === null ? null : <small>yd/s²</small>}</dd></div>
            <div><dt>Field x</dt><dd>{entity.x.toFixed(1)} <small>yd</small></dd></div>
            <div><dt>Field y</dt><dd>{entity.y.toFixed(1)} <small>yd</small></dd></div>
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
  const suffix = down === 1 ? "st" : down === 2 ? "nd" : down === 3 ? "rd" : "th";
  return `${down}${suffix} & ${yards ?? "goal"}`;
}

function formatYards(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)} yd`;
}

function signed(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(1)}`;
}
