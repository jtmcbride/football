import { memo, useEffect, useMemo, useRef, useState } from "react";
import { fetchJson, fetchTrackingPlay } from "../lib/catalog";
import { buildRouteSearchUrl, overlayDash, routeKey, routeLabel } from "../lib/routes";
import type { RoutePage, RoutePath } from "../lib/routes";
import type { TrackingPlay } from "../lib/types";

interface Props {
  current: RoutePath | null;
  overlays: RoutePath[];
  onOverlaysChange: (routes: RoutePath[]) => void;
  onSelectPlay: (play: TrackingPlay) => void;
}

export const RouteAtlas = memo(function RouteAtlas({ current, overlays, onOverlaysChange, onSelectPlay }: Props) {
  const [route, setRoute] = useState("");
  const [coverage, setCoverage] = useState("");
  const [coverageType, setCoverageType] = useState("");
  const [similar, setSimilar] = useState(false);
  const [page, setPage] = useState(1);
  const [response, setResponse] = useState<{ url: string; value: RoutePage } | null>(null);
  const [failure, setFailure] = useState<{ url: string; message: string } | null>(null);
  const [opening, setOpening] = useState<string | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const playRequest = useRef<AbortController | null>(null);
  const url = buildRouteSearchUrl(route, coverage, page, similar && current ? current : undefined, coverageType);
  const result = response?.url === url ? response.value : null;
  const error = failure?.url === url ? failure.message : null;
  const loading = !result && !error;

  useEffect(() => {
    const controller = new AbortController();
    fetchJson<RoutePage>(url, controller.signal).then((value) => {
      if (!controller.signal.aborted) setResponse({ url, value });
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setFailure({ url, message: reason instanceof Error ? reason.message : "Route search failed." });
    });
    return () => controller.abort();
  }, [url]);
  useEffect(() => () => playRequest.current?.abort(), []);

  const openPlay = async (item: RoutePath) => {
    playRequest.current?.abort();
    const controller = new AbortController();
    playRequest.current = controller;
    setOpening(routeKey(item));
    setOpenError(null);
    try {
      const play = await fetchTrackingPlay(item.gameId, item.playId, controller.signal);
      if (controller.signal.aborted) return;
      onSelectPlay(play);
      document.getElementById("replay")?.scrollIntoView({ block: "start" });
    } catch (reason) {
      if (!controller.signal.aborted) setOpenError(reason instanceof Error ? reason.message : "Play could not be loaded.");
    } finally {
      if (!controller.signal.aborted) setOpening(null);
    }
  };

  const options = response?.value;
  return (
    <section id="route-atlas" className="route-atlas" aria-labelledby="route-atlas-title">
      <div className="atlas-heading">
        <div><p className="eyebrow">TARGETED RECEIVERS · OBSERVED PATHS</p><h2 id="route-atlas-title">Route atlas</h2></div>
        <p>{options ? `${options.indexed.toLocaleString()} comparable routes / ${options.catalogPlays.toLocaleString()} catalog plays` : "Searching the local route catalog"}</p>
      </div>
      <div className="atlas-controls">
        <label>Target route<select aria-label="Target route" value={route} onChange={(event) => { setRoute(event.target.value); setPage(1); }}>
          <option value="">All routes</option>{options?.routeOptions.map((value) => <option key={value} value={value}>{routeLabel(value)}</option>)}
        </select></label>
        <label>Coverage<select aria-label="Route coverage" value={coverage} onChange={(event) => { setCoverage(event.target.value); setPage(1); }}>
          <option value="">All coverages</option>{options?.coverageOptions.map((value) => <option key={value} value={value}>{routeLabel(value)}</option>)}
        </select></label>
        <label>Coverage scheme<select aria-label="Coverage scheme" value={coverageType} onChange={(event) => { setCoverageType(event.target.value); setPage(1); }}>
          <option value="">All schemes</option>{options?.coverageTypeOptions.map((value) => <option key={value} value={value}>{routeLabel(value)}</option>)}
        </select></label>
        <button type="button" aria-pressed={!similar} onClick={() => { setSimilar(false); setPage(1); }}>Browse routes</button>
        <button type="button" aria-pressed={similar} disabled={!current} onClick={() => { setSimilar(true); setPage(1); }}>Find similar to current play</button>
      </div>
      {!current ? <p className="atlas-note">Open an indexed pass-window play to compare its targeted receiver. A continuous pre-throw path and known direction are required.</p> : null}
      <div className="atlas-layout">
        <div className="atlas-plot-column">
          {current || overlays.length ? <RoutePlot current={current} overlays={overlays} /> : <p className="atlas-empty">Open a route from the catalog to start comparing paths.</p>}
          <div className="atlas-legend">
            {current ? <span className="atlas-reference">Current: {current.receiverName} · {routeLabel(current.route)} · {current.observedSeconds.toFixed(1)} s observed</span> : null}
            {overlays.map((item, index) => <button type="button" key={routeKey(item)} onClick={() => onOverlaysChange(overlays.filter((entry) => routeKey(entry) !== routeKey(item)))}>
              <svg width="30" height="10" aria-hidden="true"><line x1="0" x2="30" y1="5" y2="5" stroke="currentColor" strokeWidth="2" strokeDasharray={overlayDash(index)} /></svg>{" "}
              Overlay {index + 1}: {item.receiverName} · {item.playId} ×
            </button>)}
          </div>
          <p className="atlas-note">Overlay up to 3 routes. Paths share the receiver’s release position; the orange path is the current play. The × marks its recorded pass landing point. Full paths include observations ahead of the replay cursor.</p>
          <details className="atlas-method"><summary>How similarity works</summary>
            <p>Pre-throw coordinates only, normalized so the offense moves right. Each receiver’s position at release is the origin. Search compares 21 equally spaced fractions of the observed time window using RMS Euclidean distance in yards; lower is closer. Distances are not scaled, and lateral direction is not mirrored.</p>
            <p>Durations can differ: this compares path shape, not speed or synchronized time. Thumbnails fit each route independently; overlays use a shared yard scale. Comparison paths use the 21 indexed samples. Route and coverage are source annotations used as filters, not ranking inputs. The route label applies only to the targeted receiver. Landing points and flight paths do not affect ranking.</p>
            <p>Source: the loaded pass-window release. Snap time is unavailable; release is derived from the input-window boundary. Invalid plays, ambiguous targets, unknown direction, and interrupted target paths are excluded. Results describe this release, not all NFL routes.</p>
          </details>
        </div>
        <div className="atlas-results" aria-busy={loading}>
          {loading ? <p role="status">Loading routes…</p> : null}
          {error ? <p role="alert">{error}</p> : null}
          {openError ? <p role="alert">{openError}</p> : null}
          {result && !result.supported ? <p>This catalog has no pass-window target labels. Load the 2026 pass-window catalog to use the route atlas.</p> : null}
          {result?.supported && !result.items.length ? <p>No comparable routes match these filters.</p> : null}
          {result?.items.map((item) => {
            const key = routeKey(item);
            const checked = overlays.some((entry) => routeKey(entry) === key);
            const isCurrent = current && routeKey(current) === key;
            return <article className="atlas-result" key={key}>
              <RouteThumbnail route={item} />
              <div className="atlas-result-copy"><h3>{item.receiverName} <span>{routeLabel(item.route)}</span></h3>
                <p>{item.offense} vs {item.defense} · {item.season} W{item.week} · Play {item.playId}</p>
                <p>{routeLabel(item.coverageType ?? item.coverage)} · {item.observedSeconds.toFixed(1)} s observed</p>
                {item.distanceYards != null ? <strong>{item.distanceYards.toFixed(2)} yd shape distance</strong> : null}
              </div>
              <div className="atlas-result-actions">
                <label><input type="checkbox" checked={checked} disabled={Boolean(isCurrent) || (!checked && overlays.length >= 3)} onChange={() => onOverlaysChange(checked ? overlays.filter((entry) => routeKey(entry) !== key) : [...overlays, item])} /> Overlay</label>
                <button type="button" disabled={opening !== null} onClick={() => void openPlay(item)}>{opening === key ? "Loading…" : "Open replay"}</button>
              </div>
            </article>;
          })}
          {result?.supported ? <div className="atlas-pagination">
            <button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button>
            <span>{result.total.toLocaleString()} {similar ? "matches" : "routes"} · Page {page} / {Math.max(1, Math.ceil(result.total / result.pageSize))}</span>
            <button type="button" disabled={page * result.pageSize >= result.total} onClick={() => setPage(page + 1)}>Next</button>
          </div> : null}
        </div>
      </div>
    </section>
  );
});

function plotGeometry(routes: RoutePath[], landing?: { x: number; y: number } | null) {
  const points = routes.flatMap((route) => route.points).concat(landing ? [landing] : []);
  const minX = Math.floor(Math.min(-5, ...points.map((point) => point.x)) / 5) * 5 - 5;
  const maxX = Math.ceil(Math.max(5, ...points.map((point) => point.x)) / 5) * 5 + 5;
  const minY = Math.floor(Math.min(-5, ...points.map((point) => point.y)) / 5) * 5 - 5;
  const maxY = Math.ceil(Math.max(5, ...points.map((point) => point.y)) / 5) * 5 + 5;
  const scale = Math.min(480 / (maxX - minX), 260 / (maxY - minY));
  const x = (value: number) => 70 + (480 - (maxX - minX) * scale) / 2 + (value - minX) * scale;
  const y = (value: number) => 25 + (260 - (maxY - minY) * scale) / 2 + (maxY - value) * scale;
  return { minX, maxX, minY, maxY, x, y };
}

function RoutePlot({ current, overlays }: { current: RoutePath | null; overlays: RoutePath[] }) {
  const all = useMemo(() => current ? [current, ...overlays] : overlays, [current, overlays]);
  const plot = useMemo(() => plotGeometry(all, current?.ballLanding), [all, current]);
  const { x, y } = plot;
  const xTicks = Array.from({ length: Math.floor((plot.maxX - plot.minX) / 5) + 1 }, (_, index) => plot.minX + index * 5);
  const yTicks = Array.from({ length: Math.floor((plot.maxY - plot.minY) / 5) + 1 }, (_, index) => plot.minY + index * 5);
  return <svg className="atlas-plot" viewBox="0 0 600 350" role="img" aria-label="Observed receiver paths aligned at release, distances in yards">
    {xTicks.map((value) => <g key={`x-${value}`}><line className="atlas-grid" x1={x(value)} x2={x(value)} y1={y(plot.minY)} y2={y(plot.maxY)} /><text x={x(value)} y="305" textAnchor="middle">{value}</text></g>)}
    {yTicks.map((value) => <g key={`y-${value}`}><line className="atlas-grid" x1={x(plot.minX)} x2={x(plot.maxX)} y1={y(value)} y2={y(value)} /><text x="50" y={y(value) + 4} textAnchor="end">{value}</text></g>)}
    {all.map((route) => <polyline key={routeKey(route)} className={route === current ? "atlas-path reference" : "atlas-path comparison"}
      points={route.points.map((point) => `${x(point.x)},${y(point.y)}`).join(" ")}
      strokeDasharray={route === current ? undefined : overlayDash(overlays.indexOf(route))} />)}
    <circle cx={x(0)} cy={y(0)} r="5" className="atlas-origin" /><text x={x(0) + 8} y={y(0) - 10}>Release</text>
    {current?.ballLanding ? <text className="atlas-landing" x={x(current.ballLanding.x)} y={y(current.ballLanding.y) + 5} textAnchor="middle">×<title>Recorded landing point of the current pass</title></text> : null}
    <text x="310" y="335" textAnchor="middle">Downfield offset from release (yd)</text>
    <text transform="translate(16 160) rotate(-90)" textAnchor="middle">Lateral offset (yd)</text>
  </svg>;
}

function RouteThumbnail({ route }: { route: RoutePath }) {
  const { x, y } = plotGeometry([route]);
  return <svg className="atlas-thumbnail" viewBox="0 0 600 320" aria-hidden="true">
    <polyline points={route.points.map((point) => `${x(point.x)},${y(point.y)}`).join(" ")} />
    <circle cx={x(0)} cy={y(0)} r="13" />
  </svg>;
}
