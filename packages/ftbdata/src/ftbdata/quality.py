"""Per-play tracking quality checks and provenance.

``assess_play`` inspects a normalized ``TrackingPlay`` dictionary (plus a few
observations about the raw source rows that normalization would otherwise hide)
and returns a list of named checks. The same function serves every play
interactively and every play during ingestion, so a stored report and a served
play cannot disagree.

Check statuses, mildest to most severe:

``pass``         the property holds
``info``         worth disclosing, but does not weaken the data
``unavailable``  the check could not be evaluated for this play
``warning``      the play is usable but incomplete or suspect
``error``        the play is corrupt and should not feed an analysis

A play's overall status is ``invalid`` when any check is an error,
``incomplete`` when any is a warning, and ``valid`` otherwise. Generated demo
plays are always ``generated``.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from importlib import metadata
from typing import Any, Iterable

from .field import FIELD_LENGTH, FIELD_WIDTH

QUALITY_VERSION = 1

TRACKING_HZ = 10
FRAME_MS = 1000 // TRACKING_HZ
EXPECTED_PLAYERS = 22

#: Players legitimately step a little outside the lines; beyond these margins the data is suspect.
COORDINATE_NOTE_YARDS = 0.0
COORDINATE_WARN_YARDS = 2.0
COORDINATE_ERROR_YARDS = 10.0

#: Timestamp spacing may jitter slightly around 100 ms.
CADENCE_TOLERANCE_MS = 25.0

#: The football should sit on the line of scrimmage when it is snapped.
YARDLINE_TOLERANCE_YARDS = 3.0

#: ``dir`` is the heading of motion. Only fast, clearly moving players are compared.
HEADING_MIN_SPEED = 2.0
HEADING_MIN_DISPLACEMENT = 0.3
HEADING_TOLERANCE_DEGREES = 60.0
HEADING_MIN_SAMPLES = 10
HEADING_MIN_AGREEMENT = 0.8

PASS, INFO, UNAVAILABLE, WARNING, ERROR = "pass", "info", "unavailable", "warning", "error"
VALID, INCOMPLETE, INVALID, GENERATED = "valid", "incomplete", "invalid", "generated"
PLAY_STATUSES = (VALID, INCOMPLETE, INVALID)
CHECK_IDS = (
    "rows",
    "coordinates",
    "frame-order",
    "cadence",
    "identity",
    "ball",
    "events",
    "entity-count",
    "direction",
    "yardline",
    "heading",
    "source-fields",
)

#: Source columns whose absence limits what can be measured, keyed by the name served to clients.
SOURCE_FIELDS = {
    "speed": "s",
    "acceleration": "a",
    "orientation": "o",
    "direction": "dir",
    "event": "event",
    "time": "time",
    "playDirection": "playDirection",
}

_PRE_SNAP_EVENTS = {"huddle_break_offense", "line_set", "man_in_motion", "shift", "motion_shift"}
_POST_SNAP_EVENTS = {
    "play_action", "handoff", "run", "pass_forward", "autoevent_passforward", "pass_arrived",
    "pass_outcome_caught", "pass_outcome_incomplete", "pass_outcome_interception",
    "pass_outcome_touchdown", "qb_sack", "qb_strip_sack", "first_contact", "tackle",
}
_RELEASE_EVENTS = {"pass_forward", "autoevent_passforward"}
_ARRIVAL_EVENTS = {"pass_arrived"}
_OUTCOME_PREFIX = "pass_outcome_"


@dataclass
class SourceObservations:
    """Facts about the raw rows that the normalized play no longer shows."""

    rows: int = 0
    rows_without_frame: int = 0
    rows_unparseable: int = 0
    duplicate_rows: int = 0
    frame_regressions: int = 0
    conflicting_event_frames: int = 0
    frame_times_ms: dict[int, float] = field(default_factory=dict)
    field_values: Counter[str] = field(default_factory=Counter)
    headers: frozenset[str] = frozenset()
    rotated: bool = False


def software() -> dict[str, str]:
    try:
        version = metadata.version("football-analysis")
    except metadata.PackageNotFoundError:
        version = "unknown"
    return {"name": "football-analysis", "version": version}


def assess_play(
    play: dict[str, Any],
    observations: SourceObservations | None = None,
    *,
    generated: bool = False,
) -> dict[str, Any]:
    """Run every check and return ``{"version", "status", "errors", "warnings", "checks"}``."""

    frames = play.get("frames") or []
    if not frames:
        return failed_validation("No tracking frames could be read for this play")

    checks = [
        _rows(observations),
        _coordinates(frames),
        _frame_order(observations),
        _cadence(frames, observations),
        _identity(frames),
        _ball(frames),
        _events(frames, observations),
        _entity_count(frames),
        _direction(play, observations),
        _yardline(play, frames),
        _heading(frames, generated),
        _source_fields(observations),
    ]
    return _validation(checks, generated)


def _validation(checks: list[dict[str, Any]], generated: bool) -> dict[str, Any]:
    errors = sum(1 for item in checks if item["status"] == ERROR)
    warnings = sum(1 for item in checks if item["status"] == WARNING)
    status = GENERATED if generated else INVALID if errors else INCOMPLETE if warnings else VALID
    return {
        "version": QUALITY_VERSION,
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def failed_validation(message: str) -> dict[str, Any]:
    """The validation of a play that could not be read or assessed at all."""
    return _validation([_check("rows", "Source rows", ERROR, message)], False)


def _check(check_id: str, label: str, status: str, detail: str, count: int | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"id": check_id, "label": label, "status": status, "detail": detail}
    if count is not None:
        result["count"] = count
    return result


def _worst(statuses: Iterable[str]) -> str:
    rank = {PASS: 0, INFO: 1, UNAVAILABLE: 2, WARNING: 3, ERROR: 4}
    return max(statuses, key=rank.__getitem__, default=PASS)


def _rows(obs: SourceObservations | None) -> dict[str, Any]:
    label = "Source rows"
    if obs is None:
        return _check("rows", label, UNAVAILABLE, "Source rows were not recorded")
    parts: list[tuple[str, str, int]] = []
    if obs.duplicate_rows:
        parts.append((ERROR, f"{obs.duplicate_rows} duplicate player rows within a frame", obs.duplicate_rows))
    if obs.rows_unparseable:
        parts.append((ERROR, f"{obs.rows_unparseable} rows with missing or non-numeric values were skipped", obs.rows_unparseable))
    if obs.rows_without_frame:
        parts.append((WARNING, f"{obs.rows_without_frame} rows without a frame id were skipped", obs.rows_without_frame))
    if not parts:
        return _check("rows", label, PASS, f"{obs.rows} rows read, none discarded")
    return _check(
        "rows", label, _worst(status for status, _, _ in parts),
        "; ".join(text for _, text, _ in parts), sum(count for _, _, count in parts),
    )


def _coordinates(frames: list[dict[str, Any]]) -> dict[str, Any]:
    label = "Field bounds"
    outside = 0
    non_finite = 0
    worst = 0.0
    total = 0
    for frame in frames:
        for entity in frame["entities"]:
            total += 1
            x, y = entity["x"], entity["y"]
            if not (math.isfinite(x) and math.isfinite(y)):
                non_finite += 1
                continue
            excursion = max(-x, x - FIELD_LENGTH, -y, y - FIELD_WIDTH, 0.0)
            if excursion > COORDINATE_NOTE_YARDS:
                outside += 1
                worst = max(worst, excursion)
    if non_finite:
        return _check("coordinates", label, ERROR, f"{non_finite} positions are not finite numbers", non_finite)
    if not outside:
        return _check("coordinates", label, PASS, f"All {total} positions are inside the {FIELD_LENGTH:g} × {FIELD_WIDTH:g} yd field")
    status = ERROR if worst > COORDINATE_ERROR_YARDS else WARNING if worst > COORDINATE_WARN_YARDS else INFO
    return _check(
        "coordinates", label, status,
        f"{outside} of {total} positions are outside the field (up to {worst:.1f} yd)", outside,
    )


def _frame_order(obs: SourceObservations | None) -> dict[str, Any]:
    label = "Frame order"
    if obs is None:
        return _check("frame-order", label, UNAVAILABLE, "Source row order was not recorded")
    if obs.frame_regressions:
        return _check(
            "frame-order", label, WARNING,
            f"Frames arrive out of order in the source ({obs.frame_regressions} regressions); sorted for replay",
            obs.frame_regressions,
        )
    return _check("frame-order", label, PASS, "Frames are in order and each frame id appears once")


def _cadence(frames: list[dict[str, Any]], obs: SourceObservations | None) -> dict[str, Any]:
    label = f"{TRACKING_HZ} Hz cadence"
    if len(frames) < 2:
        return _check("cadence", label, UNAVAILABLE, "A single frame has no cadence")
    ids = [frame["frameId"] for frame in frames]
    gaps = [(a, b) for a, b in zip(ids, ids[1:]) if b - a > 1]
    missing = sum(b - a - 1 for a, b in gaps)

    times = obs.frame_times_ms if obs else {}
    irregular = 0
    timed = 0
    if len(times) == len(ids):
        for a, b in zip(ids, ids[1:]):
            if b - a == 1:
                timed += 1
                if abs((times[b] - times[a]) - FRAME_MS) > CADENCE_TOLERANCE_MS:
                    irregular += 1

    problems: list[str] = []
    if missing:
        first = gaps[0]
        problems.append(
            f"{missing} frames missing in {len(gaps)} gap{'s' if len(gaps) != 1 else ''} "
            f"(first between frames {first[0]} and {first[1]})"
        )
    if irregular:
        problems.append(f"{irregular} of {timed} timestamp steps deviate from {FRAME_MS} ms")
    if problems:
        return _check("cadence", label, WARNING, "; ".join(problems), missing + irregular)
    basis = "frame ids and timestamps" if timed else "frame ids only (no usable timestamps)"
    return _check("cadence", label, PASS, f"{len(ids)} consecutive frames at {FRAME_MS} ms, from {basis}")


def _identity(frames: list[dict[str, Any]]) -> dict[str, Any]:
    label = "Player identity"
    clubs: dict[str, set[str]] = {}
    jerseys: dict[str, set[int]] = {}
    seen: Counter[str] = Counter()
    for frame in frames:
        for entity in frame["entities"]:
            if entity["kind"] != "player":
                continue
            seen[entity["id"]] += 1
            clubs.setdefault(entity["id"], set()).add(entity["club"])
            if entity["jersey"] is not None:
                jerseys.setdefault(entity["id"], set()).add(entity["jersey"])
    if not seen:
        return _check("identity", label, WARNING, "No players are tracked in this play")

    switched = sorted(player for player, values in clubs.items() if len(values) > 1)
    renumbered = sorted(player for player, values in jerseys.items() if len(values) > 1)
    dropouts = sorted(player for player, count in seen.items() if count < len(frames))
    if switched:
        return _check(
            "identity", label, ERROR,
            f"{len(switched)} tracking ids change team mid-play (e.g. {switched[0]})", len(switched),
        )
    problems: list[str] = []
    if renumbered:
        problems.append(f"{len(renumbered)} ids change jersey number (e.g. {renumbered[0]})")
    if dropouts:
        problems.append(f"{len(dropouts)} players missing from some frames (e.g. {dropouts[0]})")
    if problems:
        return _check("identity", label, WARNING, "; ".join(problems), len(renumbered) + len(dropouts))
    return _check("identity", label, PASS, f"{len(seen)} players keep one team and jersey in every frame")


def _intervals(flags: list[bool], ids: list[int]) -> list[tuple[int, int]]:
    """Frame-id ranges where ``flags`` is true."""
    ranges: list[tuple[int, int]] = []
    start: int | None = None
    for index, flagged in enumerate(flags):
        if flagged and start is None:
            start = index
        if start is not None and (not flagged or index == len(flags) - 1):
            end = index if flagged else index - 1
            ranges.append((ids[start], ids[end]))
            start = None
    return ranges


def _ball(frames: list[dict[str, Any]]) -> dict[str, Any]:
    label = "Football coverage"
    ids = [frame["frameId"] for frame in frames]
    missing_flags = [not any(entity["kind"] == "ball" for entity in frame["entities"]) for frame in frames]
    missing = sum(missing_flags)
    if missing == len(frames):
        return _check("ball", label, WARNING, "The football is not tracked in any frame", missing)
    if not missing:
        return _check("ball", label, PASS, f"Football present in all {len(frames)} frames")
    spans = _intervals(missing_flags, ids)
    shown = ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in spans[:5])
    more = f" and {len(spans) - 5} more" if len(spans) > 5 else ""
    return _check(
        "ball", label, WARNING,
        f"Football present in {len(frames) - missing} of {len(frames)} frames; missing in frames {shown}{more}",
        missing,
    )


def _events(frames: list[dict[str, Any]], obs: SourceObservations | None) -> dict[str, Any]:
    label = "Event order"
    events = [(index, frame["event"]) for index, frame in enumerate(frames) if frame["event"]]
    problems: list[str] = []
    if obs and obs.conflicting_event_frames:
        problems.append(f"{obs.conflicting_event_frames} frames carry conflicting event labels")

    snaps = [index for index, name in events if name == "ball_snap"]
    if len(snaps) > 1:
        problems.append(f"ball_snap is annotated in {len(snaps)} frames")
    if snaps:
        snap = snaps[0]
        early = sorted({name for index, name in events if name in _POST_SNAP_EVENTS and index < snap})
        late = sorted({name for index, name in events if name in _PRE_SNAP_EVENTS and index > snap})
        if early:
            problems.append(f"{', '.join(early)} occur before the snap")
        if late:
            problems.append(f"{', '.join(late)} occur after the snap")

    def first(names: set[str] | None = None, prefix: str | None = None) -> int | None:
        return next(
            (
                index for index, name in events
                if (names is not None and name in names) or (prefix is not None and name.startswith(prefix))
            ),
            None,
        )

    release, arrival, outcome = first(_RELEASE_EVENTS), first(_ARRIVAL_EVENTS), first(prefix=_OUTCOME_PREFIX)
    if release is not None and arrival is not None and arrival < release:
        problems.append("pass_arrived precedes the pass release")
    if arrival is not None and outcome is not None and outcome < arrival:
        problems.append("the pass outcome precedes pass_arrived")
    if release is not None and arrival is None and outcome is not None and outcome < release:
        problems.append("the pass outcome precedes the pass release")

    if problems:
        return _check("events", label, WARNING, "; ".join(problems), len(problems))
    if not events:
        return _check("events", label, INFO, "No events are annotated in this play")
    return _check("events", label, PASS, f"{len(events)} annotated events are in a consistent order")


def _entity_count(frames: list[dict[str, Any]]) -> dict[str, Any]:
    label = "Entity count"
    player_counts: Counter[int] = Counter()
    extra_ball = 0
    club_counts: Counter[int] = Counter()
    for frame in frames:
        players = [entity for entity in frame["entities"] if entity["kind"] == "player"]
        balls = sum(1 for entity in frame["entities"] if entity["kind"] == "ball")
        player_counts[len(players)] += 1
        extra_ball += 1 if balls > 1 else 0
        club_counts[len({entity["club"] for entity in players})] += 1

    problems: list[str] = []
    off_count = sum(count for size, count in player_counts.items() if size != EXPECTED_PLAYERS)
    if off_count:
        distribution = ", ".join(f"{size} players in {count}" for size, count in sorted(player_counts.items()))
        problems.append(f"Expected {EXPECTED_PLAYERS} players per frame; saw {distribution} frames")
    if extra_ball:
        problems.append(f"{extra_ball} frames have more than one football row")
    if set(club_counts) - {2}:
        problems.append("Players do not split into exactly two teams in every frame")
    if problems:
        return _check("entity-count", label, WARNING, "; ".join(problems), off_count + extra_ball)
    return _check("entity-count", label, PASS, f"{EXPECTED_PLAYERS} players on two teams in every frame")


def _direction(play: dict[str, Any], obs: SourceObservations | None) -> dict[str, Any]:
    label = "Play direction"
    info = play["play"]
    if info["normalizedDirection"] != "right":
        return _check(
            "direction", label, WARNING,
            "Play direction is unknown, so coordinates could not be normalized left-to-right",
        )
    original = info["originalDirection"]
    action = "rotated 180° (x, y, dir, o, yard line)" if original == "left" else "already left-to-right"
    method = (play.get("source") or {}).get("directionMethod", "source")
    if method == "inferred-line-of-scrimmage":
        return _check(
            "direction", label, INFO,
            f"Direction inferred from the line of scrimmage, not recorded in the source; {action}",
        )
    return _check("direction", label, PASS, f"Original direction {original}; {action}")


def _yardline(play: dict[str, Any], frames: list[dict[str, Any]]) -> dict[str, Any]:
    label = "Yard line cross-check"
    line = play["play"]["absoluteYardline"]
    method = (play.get("source") or {}).get("directionMethod", "source")
    if method == "inferred-line-of-scrimmage":
        return _check("yardline", label, UNAVAILABLE, "The yard line was derived from the ball, so it cannot check it")
    snap = next((frame for frame in frames if frame["event"] == "ball_snap"), None)
    ball = next((entity for entity in snap["entities"] if entity["kind"] == "ball"), None) if snap else None
    if line is None or ball is None:
        return _check("yardline", label, UNAVAILABLE, "Needs the line of scrimmage and the football at the snap")
    distance = abs(ball["x"] - line)
    if distance > YARDLINE_TOLERANCE_YARDS:
        return _check(
            "yardline", label, WARNING,
            f"At the snap the football is {distance:.1f} yd from the recorded line of scrimmage",
        )
    return _check("yardline", label, PASS, f"At the snap the football is {distance:.1f} yd from the line of scrimmage")


def _bearing(dx: float, dy: float) -> float:
    """Compass heading with 0° toward +y and 90° toward +x, matching the source ``dir`` convention."""
    return math.degrees(math.atan2(dx, dy)) % 360.0


def _heading(frames: list[dict[str, Any]], generated: bool) -> dict[str, Any]:
    label = "Heading vs. motion"
    if generated:
        return _check("heading", label, UNAVAILABLE, "Schematic headings are placeholders, not measurements")
    ids = [frame["frameId"] for frame in frames]
    by_player: dict[str, dict[int, dict[str, Any]]] = {}
    for frame in frames:
        for entity in frame["entities"]:
            if entity["kind"] == "player":
                by_player.setdefault(entity["id"], {})[frame["frameId"]] = entity

    agree = total = 0
    for positions in by_player.values():
        for frame_id in ids:
            entity, before, after = positions.get(frame_id), positions.get(frame_id - 1), positions.get(frame_id + 1)
            if not (entity and before and after) or entity["direction"] is None or entity["speed"] < HEADING_MIN_SPEED:
                continue
            dx, dy = after["x"] - before["x"], after["y"] - before["y"]
            if math.hypot(dx, dy) < HEADING_MIN_DISPLACEMENT:
                continue
            difference = abs((entity["direction"] - _bearing(dx, dy) + 540.0) % 360.0 - 180.0)
            total += 1
            agree += 1 if difference <= HEADING_TOLERANCE_DEGREES else 0
    if total < HEADING_MIN_SAMPLES:
        return _check("heading", label, UNAVAILABLE, "Too little fast movement to compare heading with displacement")
    share = agree / total
    if share < HEADING_MIN_AGREEMENT:
        return _check(
            "heading", label, WARNING,
            f"Recorded heading matches the direction of motion in only {share:.0%} of {total} samples; "
            "x, y, and dir may not have been transformed together",
            total - agree,
        )
    return _check("heading", label, PASS, f"Recorded heading matches the direction of motion in {share:.0%} of {total} samples")


def _source_fields(obs: SourceObservations | None) -> dict[str, Any]:
    label = "Source fields"
    if obs is None:
        return _check("source-fields", label, UNAVAILABLE, "Source columns were not recorded")
    missing = missing_fields(obs)
    if missing:
        return _check(
            "source-fields", label, INFO,
            f"Not provided by this source: {', '.join(missing)}", len(missing),
        )
    return _check("source-fields", label, PASS, "All core motion fields are provided")


def available_fields(obs: SourceObservations | None) -> list[str]:
    """Source fields with at least one value (a present but empty column does not count)."""
    if obs is None:
        return []
    return [name for name, column in SOURCE_FIELDS.items() if obs.field_values.get(column, 0) > 0]


def missing_fields(obs: SourceObservations | None) -> list[str]:
    if obs is None:
        return []
    return [name for name in SOURCE_FIELDS if name not in available_fields(obs)]


def provenance(
    play: dict[str, Any],
    validation: dict[str, Any],
    obs: SourceObservations | None,
    *,
    tracking_file: str | None,
) -> dict[str, Any]:
    """The compact provenance summary served with a play.

    Release details are filled in by the catalog; a standalone extraction has none.
    """

    info = play["play"]
    source = play.get("source") or {}
    return {
        "release": None,
        "files": [tracking_file] if tracking_file else [],
        "software": software(),
        "direction": {
            "original": info["originalDirection"],
            "normalized": info["normalizedDirection"],
            "method": source.get("directionMethod"),
            "rotated": bool(obs.rotated) if obs else info["originalDirection"] == "left",
        },
        "fields": {"available": available_fields(obs), "missing": missing_fields(obs)},
        "nflverse": None,
        "validation": validation,
    }


@dataclass(frozen=True)
class QualityCount:
    plays: int = 0
    valid: int = 0
    incomplete: int = 0
    invalid: int = 0
    valid_rate: float | None = None

    @classmethod
    def from_statuses(cls, statuses: Iterable[str]) -> QualityCount:
        tally = Counter(statuses)
        plays = sum(tally[status] for status in PLAY_STATUSES)
        return cls(
            plays=plays,
            valid=tally[VALID],
            incomplete=tally[INCOMPLETE],
            invalid=tally[INVALID],
            valid_rate=tally[VALID] / plays if plays else None,
        )


@dataclass(frozen=True)
class CheckTally:
    id: str
    counts: dict[str, int]


@dataclass(frozen=True)
class QualityBucket:
    season: int | None
    week: int | None
    counts: QualityCount


@dataclass(frozen=True)
class QualityReport:
    """Measured tracking quality across every cataloged play, by check, season, and week."""

    version: int
    assessed_at: str | None
    overall: QualityCount
    checks: tuple[CheckTally, ...] = ()
    seasons: tuple[QualityBucket, ...] = ()
    weeks: tuple[QualityBucket, ...] = ()


def summarize(
    rows: Iterable[tuple[int | None, int | None, str, list[dict[str, Any]]]],
    assessed_at: str | None,
) -> QualityReport:
    """Aggregate ``(season, week, status, non_pass_checks)`` rows into a report."""

    materialized = list(rows)
    by_check: dict[str, Counter[str]] = {check_id: Counter() for check_id in CHECK_IDS}
    by_season: dict[int | None, list[str]] = {}
    by_week: dict[tuple[int | None, int | None], list[str]] = {}
    for season, week, status, findings in materialized:
        by_season.setdefault(season, []).append(status)
        by_week.setdefault((season, week), []).append(status)
        for finding in findings:
            by_check.setdefault(finding["id"], Counter())[finding["status"]] += 1

    def order(value: int | None) -> tuple[bool, int]:
        return (value is None, value or 0)

    total = len(materialized)
    checks = tuple(
        CheckTally(
            check_id,
            {PASS: total - sum(tally.values()), **{status: tally[status] for status in (INFO, UNAVAILABLE, WARNING, ERROR)}},
        )
        for check_id, tally in by_check.items()
        if total
    )
    return QualityReport(
        version=QUALITY_VERSION,
        assessed_at=assessed_at,
        overall=QualityCount.from_statuses(status for _, _, status, _ in materialized),
        checks=checks,
        seasons=tuple(
            QualityBucket(season, None, QualityCount.from_statuses(by_season[season]))
            for season in sorted(by_season, key=order)
        ),
        weeks=tuple(
            QualityBucket(season, week, QualityCount.from_statuses(by_week[(season, week)]))
            for season, week in sorted(by_week, key=lambda key: (order(key[0]), order(key[1])))
        ),
    )


def non_pass_checks(validation: dict[str, Any]) -> list[dict[str, Any]]:
    """The findings worth storing: every check that is not a plain pass."""
    return [item for item in validation["checks"] if item["status"] != PASS]
