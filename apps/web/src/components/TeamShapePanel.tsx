import { memo } from "react";
import type { TeamShapeSnapshot } from "../lib/teamShape";
import type { TrackingPlay } from "../lib/types";

interface TeamShapePanelProps {
  play: TrackingPlay;
  snapshot: TeamShapeSnapshot | null;
}

export const TeamShapePanel = memo(function TeamShapePanel({ play, snapshot }: TeamShapePanelProps) {
  const offenseCount = snapshot?.offense?.playerCount ?? 0;
  const defenseCount = snapshot?.defense?.playerCount ?? 0;
  const countGap = offenseCount !== 11 || defenseCount !== 11;
  const sourceCountWarning = hasQualityWarning(play, "entity-count");

  return (
    <section className="team-shape-panel" aria-label="Team shape and protection geometry">
      <header className="team-shape-heading">
        <div>
          <p className="eyebrow">TEAM SHAPE · MILESTONE 6B</p>
          <h3>Team spacing &amp; protection.</h3>
        </div>
        <p>
          <span>CURRENT SAMPLE</span>
          <b>{snapshot ? `Frame ${String(snapshot.frameId).padStart(3, "0")}` : "Unavailable"}</b>
        </p>
      </header>

      <div className="team-shape-readout">
        <ShapeReadout
          className="offense"
          label={`${play.play.offense ?? "Offense"} spread`}
          value={formatYards(snapshot?.offense?.spread ?? null)}
          note={`${offenseCount || "—"} players`}
        />
        <ShapeReadout
          className="defense"
          label={`${play.play.defense ?? "Defense"} spread`}
          value={formatYards(snapshot?.defense?.spread ?? null)}
          note={`${defenseCount || "—"} players`}
        />
        <ShapeReadout label="Centroid gap" value={formatYards(snapshot?.centroidSeparation ?? null)} />
        <ShapeReadout
          label="QB depth"
          value={formatYards(snapshot?.quarterback?.depthFromSnap ?? null, true)}
          note={quarterbackDepthNote(snapshot)}
        />
        <ShapeReadout
          label="Protection envelope"
          value={snapshot?.protection ? `${snapshot.protection.width.toFixed(1)} × ${snapshot.protection.depth.toFixed(1)} yd` : "Unavailable"}
          note={snapshot?.protection ? `QB + ${snapshot.protection.blockerCount} linemen` : protectionUnavailableNote(snapshot)}
        />
        <ShapeReadout
          label="Envelope area"
          value={snapshot?.protection ? `${snapshot.protection.area.toFixed(1)} yd²` : "Unavailable"}
        />
      </div>

      {countGap || sourceCountWarning ? (
        <p className="team-shape-caution">
          <i /> Team counts are incomplete at this frame or elsewhere in the play; centroid and spread values use only tracked players.
        </p>
      ) : null}

      <div className="team-shape-method" aria-label="Team shape metric definitions">
        <p><b>Centroid + spread</b> The centroid is the mean x/y location for a team. Spread is the RMS player distance from that point, not formation width.</p>
        <p><b>QB depth</b> Distance behind the quarterback’s own snap location after left-to-right normalization. Negative values mean he moved forward.</p>
        <p><b>Protection envelope</b> Convex hull of the quarterback and tracked offensive linemen. It describes geometry only—not assignments, pressure, or protection quality.</p>
      </div>
    </section>
  );
});

function ShapeReadout({
  className = "",
  label,
  value,
  note,
}: {
  className?: string;
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className={className}>
      <span>{label}</span>
      <strong>{value}</strong>
      {note ? <small>{note}</small> : null}
    </div>
  );
}

function formatYards(value: number | null, signed = false): string {
  if (value === null) return "Unavailable";
  return `${signed && value > 0 ? "+" : ""}${value.toFixed(1)} yd`;
}

function quarterbackDepthNote(snapshot: TeamShapeSnapshot | null): string | undefined {
  const depth = snapshot?.quarterback?.depthFromSnap;
  if (depth === null || depth === undefined) {
    switch (snapshot?.quarterbackDepthUnavailableReason) {
      case "unknown-direction": return "Play direction unavailable";
      case "missing-quarterback": return "Quarterback unavailable";
      default: return "Snap baseline unavailable";
    }
  }
  return depth >= 0 ? "behind snap point" : "ahead of snap point";
}

function protectionUnavailableNote(snapshot: TeamShapeSnapshot | null): string {
  switch (snapshot?.protectionUnavailableReason) {
    case "not-pass": return "Not a pass or sack";
    case "missing-quarterback": return "Quarterback unavailable";
    case "degenerate-geometry": return "No measurable hull";
    default: return "Needs QB + 3 linemen";
  }
}

function hasQualityWarning(play: TrackingPlay, checkId: string): boolean {
  const check = play.provenance?.validation.checks.find((candidate) => candidate.id === checkId);
  return check?.status === "warning" || check?.status === "error";
}
