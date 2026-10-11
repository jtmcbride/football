import { memo, useMemo } from "react";
import type { TrackingFrame, TrackingPlay } from "../lib/types";

const VIEW_WIDTH = 1200;
const VIEW_HEIGHT = 533;
const SCALE = 10;

interface FieldReplayProps {
  play: TrackingPlay;
  frameIndex: number;
  showLabels: boolean;
  showTrails: boolean;
  showOrientation: boolean;
  onSelectEntity: (id: string | null) => void;
  selectedEntityId: string | null;
}

export const FieldReplay = memo(function FieldReplay({
  play,
  frameIndex,
  showLabels,
  showTrails,
  showOrientation,
  onSelectEntity,
  selectedEntityId,
}: FieldReplayProps) {
  const frame = play.frames[frameIndex];
  const trails = useMemo(() => buildTrails(play.frames, frameIndex), [play.frames, frameIndex]);
  const yardLines = Array.from({ length: 13 }, (_, index) => index * 10);

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

        {showTrails ? trails.map((trail) => (
          <polyline key={trail.id} points={trail.points} className={`trail ${teamClass(trail.club, play)}`} />
        )) : null}

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
              aria-label={`${entity.name}, ${entity.speed.toFixed(1)} yards per second`}
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
      <div className="direction-ribbon" aria-hidden="true">
        <span>OFFENSE</span><i /><b>RIGHT</b>
      </div>
    </div>
  );
});

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
