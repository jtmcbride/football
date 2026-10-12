import {
  QUALITY_EXPLANATIONS,
  QUALITY_LABELS,
  checkSummary,
  contextBadge,
  describeRelease,
  findings,
  qualityBadge,
} from "../lib/provenance";
import type { ContextBadge } from "../lib/provenance";
import type { TrackingPlay } from "../lib/types";

const CONTEXT_LABELS: Record<ContextBadge, string> = {
  joined: "nflverse joined",
  conflicting: "nflverse conflict",
  unjoined: "Unjoined",
};

/** Where this play came from and whether its tracking can be trusted, with every failed check listed. */
export function ProvenanceCard({ play }: { play: TrackingPlay }) {
  const badge = qualityBadge(play);
  const context = contextBadge(play);
  const provenance = play.provenance;
  const release = provenance ? describeRelease(provenance) : null;
  const problems = provenance ? findings(provenance.validation.checks) : [];

  return (
    <section className={`provenance-card ${badge}`} aria-label="Data provenance">
      <p className="eyebrow">DATA PROVENANCE</p>
      <div className="badge-row">
        <span className={`quality-badge ${badge}`}>{QUALITY_LABELS[badge]}</span>
        {context ? <span className={`context-badge ${context}`}>{CONTEXT_LABELS[context]}</span> : null}
      </div>
      <p className="provenance-note">{QUALITY_EXPLANATIONS[badge]}</p>
      {context === "unjoined" ? (
        <p className="provenance-note">No nflverse play-by-play row is attached, so result and situation fields come from the tracking release only.</p>
      ) : null}

      {provenance ? (
        <>
          <details className="check-list" open={badge === "incomplete" || badge === "invalid"}>
            <summary>{checkSummary(provenance.validation.checks)}</summary>
            {problems.length > 0 ? (
              <ul>
                {problems.map((check) => (
                  <li key={check.id} className={check.status}>
                    <b>{check.label}</b>
                    <span className="check-status">{check.status}</span>
                    <small>{check.detail}</small>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="provenance-note">No findings.</p>
            )}
          </details>

          <dl className="context-grid provenance-grid">
            {release ? <div className="wide"><dt>Release</dt><dd title={release}>{release}</dd></div> : null}
            {provenance.release ? (
              <div><dt>Fingerprint</dt><dd title={provenance.release.fingerprint}>{provenance.release.fingerprint.slice(0, 12)}</dd></div>
            ) : null}
            {provenance.release ? (
              <div><dt>Ingested</dt><dd>{provenance.release.ingestedAt.slice(0, 10)}</dd></div>
            ) : null}
            <div>
              <dt>Direction</dt>
              <dd>{provenance.direction.original} → {provenance.direction.normalized}{provenance.direction.rotated ? " (rotated)" : ""}</dd>
            </div>
            <div><dt>Software</dt><dd>{provenance.software.name} {provenance.software.version}</dd></div>
            {provenance.files.length > 0 ? (
              <div className="wide"><dt>Source files</dt><dd title={provenance.files.join(", ")}>{provenance.files.join(", ")}</dd></div>
            ) : null}
            {provenance.fields.available.length + provenance.fields.missing.length > 0 ? (
              <div className="wide">
                <dt>Source fields</dt>
                <dd>
                  {provenance.fields.available.length} available
                  {provenance.fields.missing.length > 0 ? ` · missing ${provenance.fields.missing.join(", ")}` : ""}
                </dd>
              </div>
            ) : null}
          </dl>
        </>
      ) : null}
    </section>
  );
}
