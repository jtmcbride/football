import { memo, useEffect, useState } from "react";
import { fetchJson } from "../lib/catalog";
import { yards, type FlightReport, type Ghost } from "../lib/flight";
import type { TrackingPlay } from "../lib/types";

export const FlightLab = memo(function FlightLab({ play, frameIndex, ghosts, onFrameChange, onSelectEntity }: {
  play: TrackingPlay; frameIndex: number; ghosts: Ghost[];
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
  const forecast = play.flightForecast;
  const release = play.frames.findIndex((frame) => frame.frameId === forecast?.releaseFrameId);
  const arrival = play.frames.findIndex((frame) => frame.frameId === play.play.passWindow?.arrivalFrameId);
  const seconds = release >= 0 ? (play.frames[frameIndex].frameId - play.frames[release].frameId) / 10 : null;
  const fingerprint = play.provenance?.release?.fingerprint;
  const matching = report && fingerprint === report.fingerprint;
  const cohort = matching ? report.heldOutGames.includes(play.play.gameId) ? "Held-out game" : "Development game" : "Split membership unavailable";

  return <section className="analysis-panel flight-lab" id="flight-lab" aria-label="Pass-flight prediction lab">
    <header className="analysis-heading"><div><p className="eyebrow">PASS-FLIGHT LAB · CONSTANT VELOCITY</p>
      <h3>Where momentum would take them.</h3></div><p className="analysis-window">{cohort}</p></header>
    <p>Hollow white ghosts project each source-selected player from release. Dashed connectors measure the distance to their observed position. Use the Ghosts overlay switch above the field.</p>
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
      <p>At the final input frame, freeze speed and movement direction: x(t) = x₀ + s sin(dir) t; y(t) = y₀ + s cos(dir) t. Direction is clockwise from +y. Coordinates and directions rotate together for leftward plays. No acceleration or body orientation is used; missing release speed/direction makes a player unavailable.</p>
      <p>Time is source frame offset / 10, from derived release through the last observed output frame. Landing position, route labels, future positions, and flight duration are not forecast inputs. Forecasts continue through missing observations; errors stay unavailable there. Off-field projections are not clipped.</p>
      <p>Coordinate RMSE averages squared x and y errors separately before taking the square root. Mean distance averages Euclidean errors per observed player-frame; final distance averages available errors at the play’s last output frame. These are yards. Longer flights carry more weight in frame-level scores.</p>
    </details>
    <div className="flight-benchmark">
      <p className="eyebrow">HELD-OUT GAME BENCHMARK</p>
      {error ? <p>{error}</p> : !report ? <p>Loading measurements…</p> : <>
        <p>{report.heldOutGames.length} held-out games · {report.developmentGames.length} development games · {(report.counts.scoredPlays ?? 0).toLocaleString()} scored plays · {report.overall.samples.toLocaleString()} player-frames. No fitted parameters.</p>
        <div className="analysis-readout">
          <div><span>Coordinate RMSE</span><b>{yards(report.overall.coordinateRmse)}</b></div>
          <div><span>Mean distance</span><b>{yards(report.overall.meanDistance)}</b></div>
          <div><span>Final distance</span><b>{yards(report.overall.finalDistance)}</b></div>
        </div>
        <HorizonPlot report={report} />
        <details><summary>Coverage, split, and source limitations</summary>
          <p>{report.overall.missingSamples.toLocaleString()} missing player-frames; {(report.counts.unavailablePlayers ?? 0).toLocaleString()} players without usable release inputs; {Object.values(report.skippedPlays).reduce((sum, n) => sum + n, 0)} excluded plays.</p>
          {Object.entries(report.skippedPlays).map(([reason, count]) => <p key={reason}>{reason}: {count}</p>)}
          {report.byRole.map((role) => <p key={role.role}>{role.role}: coordinate RMSE {yards(role.coordinateRmse)} · {role.samples.toLocaleString()} player-frames</p>)}
          <p>Game split: {report.splitRule}. The report records every game ID and source fingerprint. Generated {new Date(report.createdAt).toLocaleString()}.</p>
          {report.limitations.map((note) => <p key={note}>{note}</p>)}
          <a href="/api/flight-report" target="_blank" rel="noreferrer">Open full evaluation JSON</a>
        </details>
      </>}
    </div>
  </section>;
});

function HorizonPlot({ report }: { report: FlightReport }) {
  const points = report.byHorizon.filter((row) => row.coordinateRmse !== null);
  if (!points.length) return <p>No scored horizons.</p>;
  const maxX = Math.max(0.1, ...points.map((point) => point.seconds));
  const maxY = Math.max(1, ...points.map((point) => point.coordinateRmse!));
  return <figure className="flight-horizon"><svg viewBox="0 0 700 200" role="img" aria-label="Held-out coordinate RMSE by seconds after release">
    {[0, 0.5, 1].map((fraction) => <g key={fraction}>
      <line x1="55" x2="680" y1={150 - fraction * 120} y2={150 - fraction * 120} />
      <text x="48" y={154 - fraction * 120} textAnchor="end">{(fraction * maxY).toFixed(1)}</text>
      <text x={55 + fraction * 625} y="174" textAnchor="middle">{(fraction * maxX).toFixed(1)} s</text>
    </g>)}
    <text x="55" y="17">COORDINATE RMSE · YARDS</text>
    {points.map((point) => <circle key={point.seconds} cx={55 + point.seconds / maxX * 625}
      cy={150 - point.coordinateRmse! / maxY * 120} r="3">
      <title>{point.seconds.toFixed(1)} s: {yards(point.coordinateRmse)} · {point.samples.toLocaleString()} player-frames</title>
    </circle>)}
  </svg><figcaption>Error by forecast horizon. Later points contain only longer flights; hover for sample counts.</figcaption>
  <details><summary>Horizon values and sample counts</summary><div className="flight-horizon-values">
    {points.map((point) => <p key={point.seconds}>{point.seconds.toFixed(1)} s · {yards(point.coordinateRmse)} · n={point.samples.toLocaleString()}</p>)}
  </div></details></figure>;
}
