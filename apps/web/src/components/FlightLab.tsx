import { memo, useEffect, useState } from "react";
import { fetchJson } from "../lib/catalog";
import { BASELINE_LABELS, forecastFor, yards, type FlightBaseline, type FlightReport, type Ghost } from "../lib/flight";
import type { TrackingPlay } from "../lib/types";

export const FlightLab = memo(function FlightLab({ play, frameIndex, ghosts, baseline, onBaselineChange, onFrameChange, onSelectEntity }: {
  play: TrackingPlay; frameIndex: number; ghosts: Ghost[];
  baseline: FlightBaseline; onBaselineChange: (baseline: FlightBaseline) => void;
  onFrameChange: (index: number) => void; onSelectEntity: (id: string) => void;
}) {
  const [report, setReport] = useState<FlightReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetchJson<FlightReport>("/api/flight-report", controller.signal).then((next) => {
      if (!controller.signal.aborted) { setReport(next); setError(null); }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Evaluation unavailable.");
    });
    return () => controller.abort();
  }, []);
  const forecast = forecastFor(play, baseline);
  const release = play.frames.findIndex((frame) => frame.frameId === forecast?.releaseFrameId);
  const arrival = play.frames.findIndex((frame) => frame.frameId === play.play.passWindow?.arrivalFrameId);
  const seconds = release >= 0 ? (play.frames[frameIndex].frameId - play.frames[release].frameId) / 10 : null;
  const fingerprint = play.provenance?.release?.fingerprint;
  const matching = report && fingerprint === report.fingerprint;
  const cohort = matching ? report.heldOutGames.includes(play.play.gameId) ? "Held-out game" : "Development game" : "Split membership unavailable";

  return <section className="analysis-panel flight-lab" id="flight-lab" aria-label="Pass-flight prediction lab">
    <header className="analysis-heading"><div><p className="eyebrow">PASS-FLIGHT LAB · {BASELINE_LABELS[baseline]}</p>
      <h3>Where momentum would take them.</h3></div><p className="analysis-window">{cohort}</p></header>
    <p>Hollow white ghosts project each source-selected player from release. Dashed connectors measure the distance to their observed position. Use the Ghosts overlay switch above the field.</p>
    <div className="flight-controls" role="group" aria-label="Prediction baseline">
      {Object.entries(BASELINE_LABELS).map(([value, label]) => <button key={value} type="button"
        aria-pressed={baseline === value} onClick={() => onBaselineChange(value as FlightBaseline)}>{label}</button>)}
    </div>
    {!forecast || forecast.reason ? <p className="flight-unavailable">{forecast?.reason ?? "Forecast unavailable in this export. Open a pass-window play from the local catalog."}</p> : <>
      <div className="flight-controls">
        <button type="button" onClick={() => onFrameChange(release)} disabled={release < 0}>Jump to release</button>
        <button type="button" onClick={() => onFrameChange(arrival)} disabled={arrival < 0}>Jump to arrival</button>
        <b>{seconds === null ? "Unavailable" : seconds < 0 ? "Before release" : `Release + ${seconds.toFixed(1)} s`}</b>
      </div>
      {release >= 0 && arrival > release ? <label className="flight-scrub">Flight playhead
        <input aria-label="Flight playhead" type="range" min={release} max={arrival}
          value={Math.max(release, Math.min(arrival, frameIndex))}
          onChange={(event) => onFrameChange(Number(event.target.value))} />
      </label> : <p>No observed flight window; error measurements unavailable.</p>}
      {ghosts.length ? <div className="flight-players">{ghosts.map((ghost) => <button type="button" key={ghost.state.id}
        onClick={() => onSelectEntity(ghost.state.id)}>
        <span>{ghost.state.name}<small>{ghost.state.role ?? "Role unavailable"}</small></span>
        <b>{yards(ghost.error)}<small>{ghost.offField ? "Projected off field" : "Position error"}</small></b>
      </button>)}</div> : <p>Ghosts appear at release and move with the replay.</p>}
      {forecast.unavailable.map((item) => <p key={item.id}>{item.name}: {item.reason}.</p>)}
    </>}
    <details><summary>Forecast inputs and measurement definitions</summary>
      <p>At the final input frame, velocity is v = (s sin(dir), s cos(dir)). Constant velocity uses p(t) = p₀ + vt. Constant acceleration uses p(t) = p₀ + vt + ½at², where a = (v at release − v one frame earlier) / 0.1 s. Both velocity observations must be unique and exactly 0.1 s apart; missing speed/direction or history makes acceleration unavailable.</p>
      <p>Acceleration is a vector estimated from pre-throw speed and movement direction. The source’s scalar acceleration and body orientation are unused. Direction is clockwise from +y; positions and vectors rotate together for leftward plays. Acceleration stays fixed in field coordinates without damping or speed caps, so forecasts can reverse or overshoot.</p>
      <p>Time is source frame offset / 10, from derived release through the last observed output frame. Landing position, route labels, future positions, and flight duration are not forecast inputs. Forecasts continue through missing observations; errors stay unavailable there. Off-field projections are not clipped.</p>
      <p>Coordinate RMSE averages squared x and y errors separately before taking the square root. Mean distance averages Euclidean errors per observed player-frame; final distance averages available errors at the play’s last output frame. These are yards. Longer flights carry more weight in frame-level scores.</p>
    </details>
    <div className="flight-benchmark">
      <p className="eyebrow">HELD-OUT GAME BENCHMARK</p>
      {error ? <p>{error}</p> : !report ? <p>Loading measurements…</p> : <>
        <p>{report.heldOutGames.length} held-out games · {report.developmentGames.length} development games · {(report.comparison.counts.scoredPlays ?? 0).toLocaleString()} paired plays · {report.comparison.baselines["constant-velocity"].overall.samples.toLocaleString()} matching player-frames. No fitted parameters.</p>
        <p>Both baselines use identical players, frames, and observed labels. {(report.comparison.counts.velocityOnlyPlayers ?? 0).toLocaleString()} velocity-only trajectories are excluded from this paired comparison; their original velocity scores remain in the JSON reference.</p>
        {(Object.keys(BASELINE_LABELS) as FlightBaseline[]).map((key) => {
          const scores = report.comparison.baselines[key].overall;
          return <div className={`flight-score-row ${key}`} key={key}>
            <h4>{BASELINE_LABELS[key]}</h4><div className="analysis-readout">
              <div><span>Coordinate RMSE</span><b>{yards(scores.coordinateRmse)}</b></div>
              <div><span>Mean distance</span><b>{yards(scores.meanDistance)}</b></div>
              <div><span>Final distance</span><b>{yards(scores.finalDistance)}</b></div>
            </div>
          </div>;
        })}
        <p className="flight-delta">Acceleration − velocity: RMSE {signedYards(report.comparison.delta.coordinateRmse)} · mean {signedYards(report.comparison.delta.meanDistance)} · final {signedYards(report.comparison.delta.finalDistance)}. Negative favors acceleration.</p>
        <p>Per-game RMSE: acceleration improves {report.comparison.gameResults.improved ?? 0}, worsens {report.comparison.gameResults.worse ?? 0}, ties {report.comparison.gameResults.tied ?? 0} games.</p>
        <HorizonPlot report={report} />
        <details><summary>Coverage, split, and source limitations</summary>
          <p>{report.overall.missingSamples.toLocaleString()} missing player-frames; {(report.counts.unavailablePlayers ?? 0).toLocaleString()} players without usable release inputs; {Object.values(report.skippedPlays).reduce((sum, n) => sum + n, 0)} excluded plays.</p>
          {Object.entries(report.skippedPlays).map(([reason, count]) => <p key={reason}>{reason}: {count}</p>)}
          {Object.entries(report.comparison.unavailableReasons).map(([reason, count]) => <p key={reason}>{reason}: {count} trajectories</p>)}
          {(Object.keys(BASELINE_LABELS) as FlightBaseline[]).map((key) => <div key={key}>
            <b>{BASELINE_LABELS[key]} · paired roles</b>
            {report.comparison.baselines[key].byRole.map((role) => <p key={role.role}>{role.role}: coordinate RMSE {yards(role.coordinateRmse)} · {role.samples.toLocaleString()} player-frames</p>)}
          </div>)}
          <p>Game split: {report.splitRule}. The report records every game ID and source fingerprint. Generated {new Date(report.createdAt).toLocaleString()}.</p>
          {report.limitations.map((note) => <p key={note}>{note}</p>)}
          <a href="/api/flight-report" target="_blank" rel="noreferrer">Open full evaluation JSON</a>
        </details>
      </>}
    </div>
  </section>;
});

function HorizonPlot({ report }: { report: FlightReport }) {
  const velocity = report.comparison.baselines["constant-velocity"].byHorizon;
  const acceleration = report.comparison.baselines["constant-acceleration"].byHorizon;
  const points = [...velocity, ...acceleration].filter((row) => row.coordinateRmse !== null);
  if (!points.length) return <p>No paired scored horizons.</p>;
  const maxX = Math.max(0.1, ...points.map((point) => point.seconds));
  const maxY = Math.max(1, ...points.map((point) => point.coordinateRmse!));
  return <figure className="flight-horizon"><svg viewBox="0 0 700 200" role="img" aria-label="Held-out coordinate RMSE by seconds after release">
    {[0, 0.5, 1].map((fraction) => <g key={fraction}>
      <line x1="55" x2="680" y1={150 - fraction * 120} y2={150 - fraction * 120} />
      <text x="48" y={154 - fraction * 120} textAnchor="end">{(fraction * maxY).toFixed(1)}</text>
      <text x={55 + fraction * 625} y="174" textAnchor="middle">{(fraction * maxX).toFixed(1)} s</text>
    </g>)}
    <text x="55" y="17">COORDINATE RMSE · YARDS</text>
    {velocity.filter((point) => point.coordinateRmse !== null).map((point) => <circle key={point.seconds} cx={55 + point.seconds / maxX * 625}
      cy={150 - point.coordinateRmse! / maxY * 120} r="3">
      <title>Velocity · {point.seconds.toFixed(1)} s: {yards(point.coordinateRmse)} · {point.samples.toLocaleString()} player-frames</title>
    </circle>)}
    {acceleration.filter((point) => point.coordinateRmse !== null).map((point) => <rect key={point.seconds} x={52 + point.seconds / maxX * 625}
      y={147 - point.coordinateRmse! / maxY * 120} width="6" height="6">
      <title>Acceleration · {point.seconds.toFixed(1)} s: {yards(point.coordinateRmse)} · {point.samples.toLocaleString()} player-frames</title>
    </rect>)}
  </svg><figcaption>Blue circles: velocity · orange squares: acceleration. Paired error by horizon; later points contain only longer flights. Hover for sample counts.</figcaption>
  <details><summary>Horizon values and sample counts</summary><div className="flight-horizon-values">
    {velocity.map((point) => <p key={point.seconds}>{point.seconds.toFixed(1)} s · velocity {yards(point.coordinateRmse)} · acceleration {yards(acceleration.find((row) => row.seconds === point.seconds)?.coordinateRmse)} · n={point.samples.toLocaleString()}</p>)}
  </div></details></figure>;
}

function signedYards(value: number | null): string {
  return value == null ? "Unavailable" : `${value > 0 ? "+" : ""}${value.toFixed(2)} yd`;
}
