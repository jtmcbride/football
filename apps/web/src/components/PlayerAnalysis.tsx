import { memo, useMemo } from "react";
import {
  nearestAnalysisFrame,
  playerAnalysis,
  type AnalysisEventKind,
  type PlayerAnalysis as PlayerAnalysisResult,
  type PlayerAnalysisSample,
} from "../lib/metrics";
import type { TrackingPlay } from "../lib/types";

const VIEW_WIDTH = 1000;
const VIEW_HEIGHT = 272;
const PLOT_LEFT = 72;
const PLOT_RIGHT = 20;
const PLOT_WIDTH = VIEW_WIDTH - PLOT_LEFT - PLOT_RIGHT;
const LANE_HEIGHT = 72;
const SPEED_TOP = 54;
const SEPARATION_TOP = 168;
const EVENT_ORDER: AnalysisEventKind[] = ["snap", "release", "arrival", "catch", "tackle"];
const EVENT_LABELS: Record<AnalysisEventKind, string> = {
  snap: "Snap",
  release: "Release",
  arrival: "Arrival",
  catch: "Catch",
  tackle: "Tackle",
};

interface PlayerAnalysisProps {
  play: TrackingPlay;
  frameIndex: number;
  selectedEntityId: string | null;
  onFrameChange: (index: number) => void;
}

export const PlayerAnalysis = memo(function PlayerAnalysis({
  play,
  frameIndex,
  selectedEntityId,
  onFrameChange,
}: PlayerAnalysisProps) {
  const analysis = useMemo(
    () => selectedEntityId ? playerAnalysis(play, selectedEntityId) : null,
    [play, selectedEntityId],
  );

  if (!analysis) {
    return (
      <section className="analysis-panel analysis-empty" aria-label="Selected player analysis">
        <div>
          <p className="eyebrow">PLAYER ANALYSIS · MILESTONE 6A</p>
          <h3>Select a player to open the motion profile.</h3>
        </div>
        <p>Choose a marker on the field. Speed, snap-relative movement, and nearest-opponent separation will stay linked to the replay playhead.</p>
      </section>
    );
  }

  const currentSample = analysis.samples.find((sample) => sample.frameIndex === frameIndex) ?? null;
  const isOffense = analysis.player.club === play.play.offense;
  const qualityStatus = play.provenance?.validation.status;
  const entityCountWarning = hasQualityWarning(play, "entity-count");
  const eventWarning = hasQualityWarning(play, "events");

  return (
    <section className="analysis-panel" aria-label={`Motion profile for ${analysis.player.name}`}>
      <header className="analysis-heading">
        <div>
          <p className="eyebrow">PLAYER ANALYSIS · MILESTONE 6A</p>
          <h3>{playerTitle(analysis)}</h3>
        </div>
        <p className="analysis-window">
          <span>ANALYSIS WINDOW</span>
          <b>{windowLabel(analysis)}</b>
        </p>
      </header>

      <div className="analysis-readout" aria-label="Current-frame measurements">
        <Readout label="Speed" value={formatMeasurement(currentSample?.speed ?? null, "yd/s")} />
        <Readout label="Route depth" value={routeValue(analysis, currentSample?.routeDepth ?? null)} />
        <Readout label="Lateral" value={routeValue(analysis, currentSample?.lateralDisplacement ?? null)} />
        <Readout label="Displacement" value={routeValue(analysis, currentSample?.totalDisplacement ?? null, false)} />
        <Readout
          label={isOffense ? "Nearest defender" : "Nearest opponent"}
          value={formatMeasurement(currentSample?.separation ?? null, "yd")}
          note={opponentLabel(currentSample)}
        />
      </div>

      <div className="analysis-events" aria-label="Tracked play events">
        {EVENT_ORDER.map((kind) => {
          const event = analysis.events.find((candidate) => candidate.kind === kind);
          return (
            <span key={kind} className={event ? `event-${kind}` : "unavailable"}>
              <b>{EVENT_LABELS[kind]}</b>
              <i>{event ? `${event.elapsedSeconds.toFixed(1)} s` : "not present"}</i>
            </span>
          );
        })}
      </div>

      <LinkedChart
        analysis={analysis}
        frameIndex={frameIndex}
        onFrameChange={onFrameChange}
      />

      <div className="analysis-availability">
        <span className={analysis.availability.acceleration ? "available" : "unavailable"}>
          <i /> Acceleration {analysis.availability.acceleration ? "available" : "unavailable in this source"}
        </span>
        {analysis.missingPlayerFrames > 0 ? (
          <span className="caution"><i /> {analysis.missingPlayerFrames} selected-player frame {analysis.missingPlayerFrames === 1 ? "gap" : "gaps"}; lines are not interpolated</span>
        ) : null}
        {entityCountWarning ? (
          <span className="caution"><i /> Entity-count gaps may affect nearest-opponent separation</span>
        ) : null}
        {eventWarning ? (
          <span className="caution"><i /> Event timing is inconsistent; markers may be misaligned</span>
        ) : null}
        {qualityStatus === "incomplete" || qualityStatus === "invalid" ? (
          <span className="caution"><i /> Tracking is {qualityStatus}; review Data provenance</span>
        ) : null}
      </div>

      <div className="analysis-method" aria-label="Metric definitions">
        <p><b>Route movement</b> Depth is x-distance and lateral is signed y-distance from the player’s snap location. Displacement is the straight-line total.</p>
        <p><b>Separation</b> Straight-line distance to the nearest tracked opponent at each frame. The opponent may change during the play.</p>
        <p><b>Window</b> Starts at the snap and ends at the first tackle, or the final tracked frame when no tackle is present. Source gaps stay visible.</p>
      </div>
      {analysis.routeUnavailableReason ? <p className="analysis-warning">{analysis.routeUnavailableReason}</p> : null}
    </section>
  );
});

function LinkedChart({
  analysis,
  frameIndex,
  onFrameChange,
}: {
  analysis: PlayerAnalysisResult;
  frameIndex: number;
  onFrameChange: (index: number) => void;
}) {
  const speedMax = niceMaximum(analysis.samples.map((sample) => sample.speed));
  const separationMax = niceMaximum(analysis.samples.map((sample) => sample.separation));
  const duration = Math.max(analysis.window.durationSeconds, 0.1);
  const x = (seconds: number) => PLOT_LEFT + (seconds / duration) * PLOT_WIDTH;
  const speedY = (value: number) => SPEED_TOP + LANE_HEIGHT - (value / speedMax) * LANE_HEIGHT;
  const separationY = (value: number) => SEPARATION_TOP + LANE_HEIGHT - (value / separationMax) * LANE_HEIGHT;
  const speedPath = linePath(analysis.samples, (sample) => sample.speed, x, speedY);
  const separationPath = linePath(analysis.samples, (sample) => sample.separation, x, separationY);
  const current = analysis.samples.find((sample) => sample.frameIndex === frameIndex) ?? null;
  const playheadX = current ? x(current.elapsedSeconds) : null;
  const timeTicks = timeTickValues(duration);

  const scrub = (clientX: number, element: SVGRectElement) => {
    const bounds = element.getBoundingClientRect();
    const viewX = ((clientX - bounds.left) / bounds.width) * VIEW_WIDTH;
    const ratio = Math.max(0, Math.min(1, (viewX - PLOT_LEFT) / PLOT_WIDTH));
    onFrameChange(nearestAnalysisFrame(analysis.samples, ratio * duration));
  };

  return (
    <div className="analysis-chart-wrap">
      <svg className="analysis-chart" viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`} aria-label="Linked speed and separation chart">
        <rect className="chart-lane" x={PLOT_LEFT} y={SPEED_TOP} width={PLOT_WIDTH} height={LANE_HEIGHT} />
        <rect className="chart-lane" x={PLOT_LEFT} y={SEPARATION_TOP} width={PLOT_WIDTH} height={LANE_HEIGHT} />

        <text className="chart-axis-title" x="10" y={SPEED_TOP + 12}>SPEED</text>
        <text className="chart-axis-unit" x="10" y={SPEED_TOP + 27}>YD/S</text>
        <text className="chart-axis-title" x="10" y={SEPARATION_TOP + 12}>SEPARATION</text>
        <text className="chart-axis-unit" x="10" y={SEPARATION_TOP + 27}>YD</text>
        <text className="chart-axis-value" x={PLOT_LEFT - 8} y={SPEED_TOP + 5} textAnchor="end">{speedMax}</text>
        <text className="chart-axis-value" x={PLOT_LEFT - 8} y={SPEED_TOP + LANE_HEIGHT} textAnchor="end">0</text>
        <text className="chart-axis-value" x={PLOT_LEFT - 8} y={SEPARATION_TOP + 5} textAnchor="end">{separationMax}</text>
        <text className="chart-axis-value" x={PLOT_LEFT - 8} y={SEPARATION_TOP + LANE_HEIGHT} textAnchor="end">0</text>

        {timeTicks.map((seconds) => (
          <g key={seconds}>
            <line className="chart-grid" x1={x(seconds)} x2={x(seconds)} y1={SPEED_TOP} y2={SEPARATION_TOP + LANE_HEIGHT} />
            <text className="chart-time" x={x(seconds)} y={VIEW_HEIGHT - 7} textAnchor="middle">{seconds.toFixed(1)}s</text>
          </g>
        ))}

        {analysis.events.map((event, index) => (
          <g className={`chart-event event-${event.kind}`} key={`${event.frameIndex}-${event.kind}`}>
            <line x1={x(event.elapsedSeconds)} x2={x(event.elapsedSeconds)} y1="38" y2={SEPARATION_TOP + LANE_HEIGHT} />
            <text x={x(event.elapsedSeconds)} y={index % 2 === 0 ? 17 : 31} textAnchor={event.elapsedSeconds === 0 ? "start" : event.elapsedSeconds === duration ? "end" : "middle"}>
              {event.label}
            </text>
          </g>
        ))}

        {speedPath ? <path className="chart-series speed" d={speedPath} /> : null}
        {separationPath ? <path className="chart-series separation" d={separationPath} /> : null}
        {playheadX !== null ? <line className="chart-playhead" x1={playheadX} x2={playheadX} y1="38" y2={SEPARATION_TOP + LANE_HEIGHT} /> : null}
        {current?.speed !== null && current?.speed !== undefined ? (
          <circle className="chart-point speed" cx={playheadX ?? 0} cy={speedY(current.speed)} r="5" />
        ) : null}
        {current?.separation !== null && current?.separation !== undefined ? (
          <circle className="chart-point separation" cx={playheadX ?? 0} cy={separationY(current.separation)} r="5" />
        ) : null}

        <rect
          className="chart-scrub-target"
          x={PLOT_LEFT}
          y="38"
          width={PLOT_WIDTH}
          height={SEPARATION_TOP + LANE_HEIGHT - 38}
          role="slider"
          tabIndex={0}
          aria-label="Analysis playhead"
          aria-valuemin={analysis.window.startIndex}
          aria-valuemax={analysis.window.endIndex}
          aria-valuenow={Math.max(analysis.window.startIndex, Math.min(analysis.window.endIndex, frameIndex))}
          aria-valuetext={current ? `Frame ${current.frameId}, ${current.elapsedSeconds.toFixed(1)} seconds from analysis start` : "Outside the analysis window"}
          onPointerDown={(event) => {
            event.currentTarget.setPointerCapture(event.pointerId);
            scrub(event.clientX, event.currentTarget);
          }}
          onPointerMove={(event) => {
            if (event.currentTarget.hasPointerCapture(event.pointerId)) scrub(event.clientX, event.currentTarget);
          }}
          onPointerUp={(event) => event.currentTarget.releasePointerCapture(event.pointerId)}
          onPointerCancel={(event) => event.currentTarget.releasePointerCapture(event.pointerId)}
          onKeyDown={(event) => {
            if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
            event.preventDefault();
            const direction = event.key === "ArrowLeft" ? -1 : 1;
            onFrameChange(Math.max(analysis.window.startIndex, Math.min(analysis.window.endIndex, frameIndex + direction)));
          }}
        />
      </svg>
      <p className="chart-instruction">Drag across either chart to scrub the replay.</p>
    </div>
  );
}

function Readout({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      {note ? <small>{note}</small> : null}
    </div>
  );
}

function playerTitle(analysis: PlayerAnalysisResult): string {
  const number = analysis.player.jersey === null ? "" : `#${analysis.player.jersey} `;
  const position = analysis.player.position ? ` · ${analysis.player.position}` : "";
  return `${number}${analysis.player.name}${position}`;
}

function windowLabel(analysis: PlayerAnalysisResult): string {
  const start = analysis.window.startEvent === "snap" ? "Snap" : "First frame";
  const end = analysis.window.endEvent === "tackle" ? "tackle" : "final frame";
  return `${start} → ${end} · ${analysis.window.durationSeconds.toFixed(1)} s`;
}

function formatMeasurement(value: number | null, unit: string, signed = false): string {
  if (value === null) return "Unavailable";
  return `${signed && value > 0 ? "+" : ""}${value.toFixed(1)} ${unit}`;
}

function routeValue(analysis: PlayerAnalysisResult, value: number | null, signed = true): string {
  if (!analysis.availability.route) return "Unavailable";
  return formatMeasurement(value, "yd", signed);
}

function opponentLabel(sample: PlayerAnalysisSample | null): string | undefined {
  if (!sample?.opponent) return undefined;
  const number = sample.opponent.jersey === null ? "" : ` #${sample.opponent.jersey}`;
  return `${sample.opponent.name}${number}`;
}

function niceMaximum(values: Array<number | null>): number {
  let maximum = 0;
  for (const value of values) {
    if (value !== null) maximum = Math.max(maximum, value);
  }
  return Math.max(2, Math.ceil(maximum / 2) * 2);
}

function timeTickValues(duration: number): number[] {
  if (duration <= 0) return [0];
  return [0, duration / 4, duration / 2, (duration * 3) / 4, duration];
}

function linePath(
  samples: PlayerAnalysisSample[],
  value: (sample: PlayerAnalysisSample) => number | null,
  x: (seconds: number) => number,
  y: (measurement: number) => number,
): string {
  let path = "";
  let drawing = false;
  for (const sample of samples) {
    const measurement = value(sample);
    if (measurement === null) {
      drawing = false;
      continue;
    }
    path += `${drawing ? " L" : "M"} ${x(sample.elapsedSeconds).toFixed(2)} ${y(measurement).toFixed(2)}`;
    drawing = true;
  }
  return path;
}

function hasQualityWarning(play: TrackingPlay, checkId: string): boolean {
  const check = play.provenance?.validation.checks.find((candidate) => candidate.id === checkId);
  return check?.status === "warning" || check?.status === "error";
}
