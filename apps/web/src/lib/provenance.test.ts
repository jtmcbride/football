import { describe, expect, it } from "vitest";
import {
  checkSummary,
  contextBadge,
  describeRelease,
  findings,
  isUnjoined,
  qualityBadge,
  qualityCoverageSummary,
} from "./provenance";
import type { QualityCoverage } from "./provenance";
import type { Provenance, QualityCheck, TrackingPlay } from "./types";

const check = (id: string, status: QualityCheck["status"]): QualityCheck => ({ id, label: id, status, detail: id });

function playWith(provenance?: Partial<Provenance>, join?: string): TrackingPlay {
  return {
    provenance: provenance && {
      release: null, files: [], software: { name: "x", version: "1" },
      direction: { original: "right", normalized: "right", method: "source", rotated: false },
      fields: { available: [], missing: [] }, nflverse: null,
      validation: { version: 1, status: "valid", errors: 0, warnings: 0, checks: [] },
      ...provenance,
    },
    enrichment: join ? { nflverse: { status: join } } : undefined,
  } as unknown as TrackingPlay;
}

describe("quality badge", () => {
  it("reports the assessed status, and 'unassessed' for exports that predate provenance", () => {
    expect(qualityBadge(playWith({ validation: { version: 1, status: "incomplete", errors: 0, warnings: 1, checks: [] } }))).toBe("incomplete");
    expect(qualityBadge(playWith({ validation: { version: 1, status: "generated", errors: 0, warnings: 0, checks: [] } }))).toBe("generated");
    expect(qualityBadge(playWith())).toBe("unassessed");
  });
});

describe("nflverse context badge", () => {
  it("distinguishes joined, conflicting and unjoined plays, and omits it outside a catalog", () => {
    expect(contextBadge(playWith({ nflverse: { status: "matched", fingerprint: "f" } }))).toBe("joined");
    expect(contextBadge(playWith({ nflverse: { status: "conflicting", fingerprint: "f" } }))).toBe("conflicting");
    expect(contextBadge(playWith({ nflverse: { status: "unmatched", fingerprint: "f" } }))).toBe("unjoined");
    expect(contextBadge(playWith({ nflverse: { status: "unavailable", fingerprint: null } }))).toBe("unjoined");
    expect(contextBadge(playWith({}, "matched"))).toBe("joined");
    expect(contextBadge(playWith({}))).toBeNull();
    expect(isUnjoined("unmatched")).toBe(true);
    expect(isUnjoined("matched")).toBe(false);
    expect(isUnjoined(undefined)).toBe(false);
  });
});

describe("findings", () => {
  const checks = [check("a", "pass"), check("b", "info"), check("c", "error"), check("d", "warning"), check("e", "unavailable")];

  it("lists non-passing checks, most severe first", () => {
    expect(findings(checks).map((item) => item.id)).toEqual(["c", "d", "e", "b"]);
  });

  it("does not mutate the served checks", () => {
    findings(checks);
    expect(checks.map((item) => item.id)).toEqual(["a", "b", "c", "d", "e"]);
  });

  it("summarizes passes and says when checks could not be evaluated", () => {
    expect(checkSummary(checks)).toBe("1 of 5 checks passed · 1 not evaluable");
    expect(checkSummary([check("a", "pass")])).toBe("1 of 1 checks passed");
  });
});

describe("catalog quality coverage", () => {
  const count = { plays: 0, valid: 0, incomplete: 0, invalid: 0, validRate: null };
  const coverage = (overall: QualityCoverage["overall"]): QualityCoverage =>
    ({ version: 1, assessedAt: null, overall, checks: [], seasons: [], weeks: [] });

  it("states measured counts and only nonzero problem categories", () => {
    expect(qualityCoverageSummary(coverage({ plays: 177, valid: 177, incomplete: 0, invalid: 0, validRate: 1 }))).toBe("177/177 plays valid");
    expect(qualityCoverageSummary(coverage({ plays: 10, valid: 6, incomplete: 3, invalid: 1, validRate: 0.6 }))).toBe("6/10 plays valid · 3 incomplete · 1 invalid");
    expect(qualityCoverageSummary(coverage(count))).toBe("tracking quality not assessed");
  });
});

describe("release description", () => {
  it("omits what is unknown instead of guessing", () => {
    const base = playWith({}).provenance!;
    expect(describeRelease(base)).toBeNull();
    const release = { name: "nfl-big-data-bowl-2025", competitionYear: 2025, season: 2022, fingerprint: "f", ingestedAt: "t" };
    expect(describeRelease({ ...base, release })).toBe("nfl-big-data-bowl-2025 · BDB 2025 · 2022 season");
    expect(describeRelease({ ...base, release: { ...release, competitionYear: null, season: null } })).toBe("nfl-big-data-bowl-2025");
  });
});
