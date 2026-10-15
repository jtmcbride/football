import { memo, useMemo } from "react";
import type { TeamShapeSnapshot } from "../lib/teamShape";
import type { TrackingFrame, TrackingPlay } from "../lib/types";
import { fieldRoutePoints, overlayDash, routeKey, routeLabel } from "../lib/routes";
import type { RoutePath } from "../lib/routes";
import type { Ghost } from "../lib/flight";

const VIEW_WIDTH = 1200;
const VIEW_HEIGHT = 533;
const SCALE = 10;

interface FieldReplayProps {
  play: TrackingPlay;
  frameIndex: number;
  showLabels: boolean;
  showTrails: boolean;
  showOrientation: boolean;
  showTeamShape: boolean;
  teamShape: TeamShapeSnapshot | null;
  currentRoute: RoutePath | null;
  routeOverlays: RoutePath[];
  showLanding: boolean;
  ghosts: Ghost[];
  showGhosts: boolean;
  onSelectEntity: (id: string | null) => void;
  selectedEntityId: string | null;
}

export const FieldReplay = memo(function FieldReplay({
  play,
  frameIndex,
  showLabels,
  showTrails,
  showOrientation,
  showTeamShape,
  teamShape,
  currentRoute,
  routeOverlays,
  showLanding,
  ghosts,
  showGhosts,
  onSelectEntity,
  selectedEntityId,
}: FieldReplayProps) {
  const frame = play.frames[frameIndex];
  const trails = useMemo(() => buildTrails(play.frames, frameIndex), [play.frames, frameIndex]);
  const yardLines = Array.from({ length: 13 }, (_, index) => index * 10);
  const window = play.play.passWindow;
  const landing = play.play.ballLanding;

  return (
    <div className="field-shell">
      <svg
        className="field"
        viewBox={`0 0 ${VIEW_WIDTH} ${VIEW_HEIGHT}`}
        role="img"
        aria-label={`Tracking field at frame ${frame.frameId}`}
        onClick={() => onSelectEntity(null)}
      >
        <defs>
          <pattern id="grass-stripe" width="100" height="533" patternUnits="userSpaceOnUse">
            <rect width="50" height="533" fill="var(--field-a)" />
            <rect x="50" width="50" height="533" fill="var(--field-b)" />
          </pattern>
          <filter id="ball-shadow" x="-100%" y="-100%" width="300%" height="300%">
            <feDropShadow dx="0" dy="2" stdDeviation="2" floodOpacity="0.35" />
          </filter>
        </defs>

        <rect width={VIEW_WIDTH} height={VIEW_HEIGHT} rx="7" fill="url(#grass-stripe)" />
        <rect x="0" y="0" width="100" height={VIEW_HEIGHT} className="end-zone" />
        <rect x="1100" y="0" width="100" height={VIEW_HEIGHT} className="end-zone" />
        {yardLines.map((yard) => (
          <g key={yard}>
            <line x1={yard * SCALE} x2={yard * SCALE} y1="0" y2={VIEW_HEIGHT} className="yard-line" />
            {yard > 10 && yard < 110 ? (
              <>
                <text x={yard * SCALE} y="48" className="yard-number top" textAnchor="middle">
                  {yard <= 60 ? yard - 10 : 110 - yard}
                </text>
                <text x={yard * SCALE} y={VIEW_HEIGHT - 34} className="yard-number" textAnchor="middle">
                  {yard <= 60 ? yard - 10 : 110 - yard}
                </text>
              </>
            ) : null}
          </g>
        ))}
        {Array.from({ length: 100 }, (_, index) => index + 10).map((yard) => (
          <g key={`hash-${yard}`} className="hashes">
            <line x1={yard * SCALE} x2={yard * SCALE} y1="190" y2="198" />
            <line x1={yard * SCALE} x2={yard * SCALE} y1="335" y2="343" />
          </g>
        ))}

        {play.play.absoluteYardline !== null ? (
          <g className="line-of-scrimmage">
            <line
              x1={play.play.absoluteYardline * SCALE}
              x2={play.play.absoluteYardline * SCALE}
              y1="0"
              y2={VIEW_HEIGHT}
            />
            <text x={play.play.absoluteYardline * SCALE + 8} y="22">LOS</text>
          </g>
        ) : null}

        {showTeamShape && teamShape ? <TeamShapeOverlay snapshot={teamShape} /> : null}

        {currentRoute ? <g className="field-route-overlay" aria-label="Full observed pre-throw routes aligned at receiver release">
          <polyline className="field-route reference" points={fieldRoutePoints(currentRoute)} />
          {routeOverlays.map((route, index) => <polyline key={routeKey(route)} className="field-route comparison"
            strokeDasharray={overlayDash(index)} points={fieldRoutePoints(route, currentRoute.release)}>
            <title>Overlay {index + 1}: {route.receiverName}, play {route.playId}</title>
          </polyline>)}
          <circle cx={currentRoute.release.x * SCALE} cy={currentRoute.release.y * SCALE} r="7" className="route-release-mark"><title>Target receiver at release</title></circle>
        </g> : null}

        {showLanding && landing ? <g className="landing-mark" transform={`translate(${landing.x * SCALE} ${landing.y * SCALE})`}>
          <title>Recorded pass landing point; not a tracked football position</title>
          <circle r="13" /><path d="M -7 -7 L 7 7 M -7 7 L 7 -7" />
          <text y="-20" textAnchor="middle">PASS LANDING</text>
        </g> : null}

        {showTrails ? trails.map((trail) => (
          <polyline key={trail.id} points={trail.points} className={`trail ${teamClass(trail.club, play)}`} />
        )) : null}

        {showGhosts ? <g className="flight-ghosts" aria-label="Constant-velocity player projections">
          {ghosts.map((ghost) => <g key={ghost.state.id} className={selectedEntityId === ghost.state.id ? "selected" : ""}>
            <title>{ghost.state.name}: constant velocity{ghost.offField ? ", projected off field" : ""}</title>
            <line className="ghost-path" x1={ghost.state.x * SCALE} y1={ghost.state.y * SCALE} x2={ghost.x * SCALE} y2={ghost.y * SCALE} />
            {ghost.actual ? <line className="ghost-error" x1={ghost.actual.x * SCALE} y1={ghost.actual.y * SCALE} x2={ghost.x * SCALE} y2={ghost.y * SCALE} /> : null}
            <circle cx={ghost.x * SCALE} cy={ghost.y * SCALE} r="17" />
          </g>)}
        </g> : null}

        {frame.entities.map((entity) => {
          const x = entity.x * SCALE;
          const y = entity.y * SCALE;
          if (entity.kind === "ball") {
            return (
              <ellipse
                key={entity.id}
                cx={x}
                cy={y}
                rx="8"
                ry="5"
                className="ball"
                filter="url(#ball-shadow)"
                transform={`rotate(25 ${x} ${y})`}
              />
            );
          }
          const isSelected = selectedEntityId === entity.id;
          const orientation = entity.orientation ?? entity.direction;
          return (
            <g
              key={entity.id}
              className={`player-mark ${teamClass(entity.club, play)} ${isSelected ? "selected" : ""}`}
              transform={`translate(${x} ${y})`}
              onClick={(event) => {
                event.stopPropagation();
                onSelectEntity(entity.id);
              }}
              role="button"
              tabIndex={0}
              aria-label={entity.speed === null ? `${entity.name}, speed not tracked` : `${entity.name}, ${entity.speed.toFixed(1)} yards per second`}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") onSelectEntity(entity.id);
              }}
            >
              {showOrientation && orientation !== null ? (
                <line
                  x1="0"
                  y1="0"
                  x2="20"
                  y2="0"
                  className="orientation"
                  transform={`rotate(${orientation - 90})`}
                />
              ) : null}
              <circle r={isSelected ? 14 : 12} />
              <text className="jersey" textAnchor="middle" y="4">
                {entity.jersey ?? entity.position ?? "•"}
              </text>
              {showLabels || isSelected ? (
                <text className="player-label" textAnchor="middle" y="-20">
                  {entity.position ?? entity.name}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      {window ? <div className="pass-window-strip">
        <span>Target route <b>{routeLabel(window.route)}</b></span>
        <span>Coverage <b>{routeLabel(window.coverageType ?? window.coverage)}</b></span>
        <span>Formation <b>{routeLabel(window.formation)}</b></span>
        <span><b>{frame.frameId < window.releaseFrameId ? "Pre-throw" : frame.frameId === window.releaseFrameId ? "Release" : frame.frameId === window.arrivalFrameId ? "Arrival boundary" : "In flight"}</b> · boundaries derived</span>
        <a href="#route-atlas">Open route atlas →</a>
        <a href="#flight-lab">Prediction lab →</a>
        {showGhosts ? <small>Hollow white: constant-velocity ghosts · dashed white: observed position error · ghosts appear at release.</small> : null}
        <small>{currentRoute ? "Solid orange: full observed target route · dashed blue: comparison routes aligned at release. " : ""}{showLanding && landing ? "Landing is recorded, not a live ball position. " : ""}Route label applies only to the targeted receiver.</small>
      </div> : null}
      <div className="direction-ribbon" aria-hidden="true">
        <span>OFFENSE</span><i /><b>{play.play.normalizedDirection === "right" ? "RIGHT" : "UNKNOWN"}</b>
      </div>
    </div>
  );
});

function TeamShapeOverlay({ snapshot }: { snapshot: TeamShapeSnapshot }) {
  return (
    <g className="team-shape-overlay" aria-hidden="true">
      {snapshot.protection ? (
        <polygon
          className="protection-envelope"
          points={snapshot.protection.points.map((point) => `${(point.x * SCALE).toFixed(1)},${(point.y * SCALE).toFixed(1)}`).join(" ")}
        />
      ) : null}
      {snapshot.offense ? <CentroidMark shape={snapshot.offense} team="offense" label="O μ" /> : null}
      {snapshot.defense ? <CentroidMark shape={snapshot.defense} team="defense" label="D μ" /> : null}
    </g>
  );
}

function CentroidMark({
  shape,
  team,
  label,
}: {
  shape: NonNullable<TeamShapeSnapshot["offense"]>;
  team: "offense" | "defense";
  label: string;
}) {
  const x = shape.centroid.x * SCALE;
  const y = shape.centroid.y * SCALE;
  return (
    <g className={`centroid-mark ${team}`}>
      <circle className="team-spread" cx={x} cy={y} r={shape.spread * SCALE} />
      <line x1={x - 10} x2={x + 10} y1={y} y2={y} />
      <line x1={x} x2={x} y1={y - 10} y2={y + 10} />
      <circle className="centroid-core" cx={x} cy={y} r="4" />
      <text x={x + 12} y={y - 10}>{label}</text>
    </g>
  );
}

function teamClass(club: string, play: TrackingPlay): string {
  if (club === play.play.offense) return "offense";
  if (club === play.play.defense) return "defense";
  return "neutral";
}

function buildTrails(frames: TrackingFrame[], frameIndex: number): Array<{ id: string; club: string; points: string }> {
  const start = Math.max(0, frameIndex - 10);
  const positions = new Map<string, { club: string; coordinates: string[] }>();
  for (let index = start; index <= frameIndex; index += 1) {
    for (const entity of frames[index].entities) {
      if (entity.kind === "ball") continue;
      const trail = positions.get(entity.id) ?? { club: entity.club, coordinates: [] };
      trail.coordinates.push(`${(entity.x * SCALE).toFixed(1)},${(entity.y * SCALE).toFixed(1)}`);
      positions.set(entity.id, trail);
    }
  }
  return Array.from(positions, ([id, value]) => ({ id, club: value.club, points: value.coordinates.join(" ") }));
}
