"""Adapter for pass-window releases such as the 2026 Big Data Bowl.

These releases split each pass play into two files per week:

``train/input_<season>_w<week>.csv``
    every frame before the throw for the passer, route runners, and coverage defenders, with
    speed, acceleration, direction, and orientation, but no football, linemen, or events
``train/output_<season>_w<week>.csv``
    x and y only, for the players to predict, from the throw until the pass arrives

Game and play context comes from ``supplementary_data.csv``. This module turns those rows into
the shapes the catalog stores and the ``TrackingPlay`` the viewer reads. Post-throw frames are
renumbered to continue after the last pre-throw frame, and their missing motion fields stay
``None`` rather than being filled in.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

from . import flight, quality, routes
from .field import FIELD_LENGTH, FIELD_WIDTH
from .tracking import build_play as build_tracking_play

TRACKING_FORMAT = "pass-window"
SUPPLEMENTARY_FILE = "supplementary_data.csv"
INPUT_PATTERN = re.compile(r"input_(\d{4})_w(\d+)\.csv$")
OUTPUT_PATTERN = re.compile(r"output_(\d{4})_w(\d+)\.csv$")
RELEASE_EVENT = "pass_forward"
ARRIVAL_EVENT = "pass_arrived"

REQUIRED_HEADERS = {
    "supplementary": {
        "game_id", "season", "week", "home_team_abbr", "visitor_team_abbr", "play_id",
        "possession_team", "defensive_team", "quarter", "down", "yards_to_go", "play_description",
    },
    "input": {
        "game_id", "play_id", "nfl_id", "frame_id", "play_direction", "absolute_yardline_number",
        "player_name", "player_position", "player_side", "x", "y", "s", "a", "dir", "o",
    },
    "output": {"game_id", "play_id", "nfl_id", "frame_id", "x", "y"},
}

COVERAGE_WARNING = (
    "Pass-window release: tracks only the passer, route runners, and coverage defenders before the throw, "
    "then x and y for the players to predict while the pass is in the air; the football, linemen, "
    "jersey numbers, and annotated events are not provided"
)

Key = tuple[str, str]


@dataclass(frozen=True)
class WeekFiles:
    season: int
    week: int
    input: Path
    output: Path | None


@dataclass(frozen=True)
class Release:
    supplementary: Path
    weeks: tuple[WeekFiles, ...]


@dataclass
class CatalogRows:
    """Everything the catalog stores for a release, in its table-row shapes."""

    games: list[tuple[Any, ...]] = field(default_factory=list)
    plays: list[tuple[Any, ...]] = field(default_factory=list)
    players: list[tuple[Any, ...]] = field(default_factory=list)
    validations: dict[Key, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    routes: list[tuple[Any, ...]] = field(default_factory=list)


def is_release(root: Path) -> bool:
    return (root / SUPPLEMENTARY_FILE).is_file() and any(_matching(root / "train", INPUT_PATTERN))


def discover(root: Path) -> tuple[Release | None, list[str]]:
    """Locate a release's files and check their headers, returning every error found."""
    errors: list[str] = []
    supplementary = root / SUPPLEMENTARY_FILE
    errors.extend(_header_errors(supplementary, REQUIRED_HEADERS["supplementary"]))
    outputs = {_season_week(path, OUTPUT_PATTERN): path for path in _matching(root / "train", OUTPUT_PATTERN)}
    weeks: list[WeekFiles] = []
    for path in _matching(root / "train", INPUT_PATTERN):
        season, week = _season_week(path, INPUT_PATTERN)
        if any(item.week == week for item in weeks):
            # The catalog finds a play's tracking file by week alone.
            errors.append(f"More than one input file claims week {week}; catalog one season at a time")
        errors.extend(_header_errors(path, REQUIRED_HEADERS["input"]))
        output = outputs.pop((season, week), None)
        if output is not None:
            errors.extend(_header_errors(output, REQUIRED_HEADERS["output"]))
        weeks.append(WeekFiles(season, week, path, output))
    errors.extend(f"{path.name} has no matching input file" for path in outputs.values())
    if errors:
        return None, errors
    return Release(supplementary, tuple(weeks)), []


def catalog_rows(release: Release) -> CatalogRows:
    """Stream every week once, building and assessing each tracked play.

    Only plays with tracking are cataloged; supplementary plays without it are counted in a warning.
    """
    supplementary = _supplementary(release.supplementary)
    result = CatalogRows(warnings=[COVERAGE_WARNING])
    players: dict[str, tuple[Any, ...]] = {}
    tracked: dict[Key, dict[str, str]] = {}
    without_output = 0
    unknown = 0

    for week in release.weeks:
        outputs = _grouped(_rows(week.output)) if week.output else {}
        for key, rows in _contiguous(_rows(week.input)):
            if key in tracked or key in result.validations:
                result.validations[key] = quality.failed_validation(
                    f"Tracking rows for this play are not contiguous in {week.input.name}"
                )
                continue
            context = supplementary.get(key)
            if context is None:
                unknown += 1
                continue
            output = outputs.get(key, [])
            without_output += 0 if output else 1
            for row in rows:
                players[row["nfl_id"]] = (
                    row["nfl_id"],
                    _text(row.get("player_name")),
                    _text(row.get("player_position")),
                    _text(row.get("player_height")),
                    _integer(row.get("player_weight")),
                    None,
                )
            try:
                play = build_play(
                    rows, output, context,
                    input_file=week.input.name, output_file=week.output.name if week.output else None,
                )
                result.validations[key] = play["provenance"]["validation"]
                route = routes.describe(play)
                if route is not None and result.validations[key]["status"] != quality.INVALID:
                    route.update({"season": _integer(context.get("season")), "week": _integer(context.get("week"))})
                    result.routes.append((*key, route["route"], route["coverage"], route["coverageType"],
                                          routes.signature(route), json.dumps(route, separators=(",", ":"))))
            except (ValueError, KeyError) as error:
                result.validations[key] = quality.failed_validation(f"Could not be assessed: {error}")
            tracked[key] = {**context, "absolute_yardline_number": rows[0].get("absolute_yardline_number", "")}

    games: dict[str, tuple[Any, ...]] = {}
    for key, context in tracked.items():
        games.setdefault(key[0], _game_row(context))
        result.plays.append(_play_row(context))
    result.games = list(games.values())
    result.players = list(players.values())

    untracked = len(supplementary) - len(tracked)
    if untracked:
        result.warnings.append(f"{untracked} supplementary plays have no tracking and were omitted from the catalog")
    if unknown:
        result.warnings.append(f"{unknown} tracked plays are absent from {SUPPLEMENTARY_FILE} and were omitted")
    if without_output:
        result.warnings.append(
            f"{without_output} plays have no post-throw output rows; their replay ends at the throw"
        )
    return result


def load_play(
    week: WeekFiles, supplementary_path: Path, game_id: str, play_id: str
) -> dict[str, Any]:
    """Build one play, streaming its week's files only until its rows have been read."""
    key = (game_id, play_id)
    context = _supplementary(supplementary_path, only=key).get(key)
    if context is None:
        raise ValueError(f"gameId={game_id}, playId={play_id} is not in {supplementary_path.name}")
    rows = _play_rows(week.input, key)
    if not rows:
        raise ValueError(f"No tracking rows found for gameId={game_id}, playId={play_id}")
    output = _play_rows(week.output, key) if week.output else []
    return build_play(
        rows, output, context,
        input_file=week.input.name, output_file=week.output.name if week.output and output else None,
    )


def iter_plays(release: Release, game_ids: set[str]) -> Iterator[dict[str, Any]]:
    """Stream selected games once for evaluation, rejecting repeated play blocks."""
    supplementary = _supplementary(release.supplementary)
    seen: set[Key] = set()
    for week in release.weeks:
        outputs = _grouped(row for row in _rows(week.output) if row["game_id"] in game_ids) if week.output else {}
        for key, rows in _contiguous(_rows(week.input)):
            if key[0] not in game_ids or key not in supplementary:
                continue
            if key in seen:
                raise ValueError(f"Repeated tracking block for {key}; cannot evaluate reliably")
            seen.add(key)
            yield build_play(rows, outputs.get(key, []), supplementary[key],
                             input_file=week.input.name, output_file=week.output.name if week.output else None)


def build_play(
    input_rows: list[dict[str, str]],
    output_rows: list[dict[str, str]],
    supplementary: dict[str, str],
    *,
    input_file: str,
    output_file: str | None,
) -> dict[str, Any]:
    """Join one play's pre-throw and in-flight rows into a normalized ``TrackingPlay``."""
    offense = _text(supplementary.get("possession_team"))
    defense = _text(supplementary.get("defensive_team"))
    players: dict[str, dict[str, str]] = {}
    tracking: list[dict[str, str]] = []
    for row in input_rows:
        players.setdefault(row["nfl_id"], row)
        tracking.append(_tracking_row(row, offense, defense))

    release_frame = max(int(row["frame_id"]) for row in input_rows)
    last_frame = release_frame
    for row in output_rows:
        player = players.get(row["nfl_id"])
        if player is None:
            continue
        frame_id = release_frame + int(row["frame_id"])
        last_frame = max(last_frame, frame_id)
        tracking.append({
            **_tracking_row(player, offense, defense),
            "frameId": str(frame_id), "x": row["x"], "y": row["y"], "s": "", "a": "", "dir": "", "o": "",
        })

    derived_events = {release_frame: RELEASE_EVENT}
    if last_frame > release_frame:
        derived_events[last_frame] = ARRIVAL_EVENT
    first = input_rows[0]
    play = build_tracking_play(
        tracking,
        frozenset(tracking[0]),
        tracking_file=input_file,
        game_key=first["game_id"],
        play_key=first["play_id"],
        play_row=_tracking_context(supplementary, first),
        game_row={},
        player_lookup={(nfl_id,): {"position": row.get("player_position", "")} for nfl_id, row in players.items()},
        tracking_format=TRACKING_FORMAT,
        pass_release_frame=release_frame,
        derived_events=derived_events,
    )
    play["play"]["ballLanding"] = _ball_landing(first, play["play"]["originalDirection"])
    targets = [nfl_id for nfl_id, row in players.items() if row.get("player_role") == "Targeted Receiver"]
    play["play"]["passWindow"] = {
        "route": _text(supplementary.get("route_of_targeted_receiver")),
        "coverage": _text(supplementary.get("team_coverage_man_zone")),
        "coverageType": _text(supplementary.get("team_coverage_type")),
        "formation": _text(supplementary.get("offense_formation")),
        "targetReceiverId": targets[0] if len(targets) == 1 else None,
        "releaseFrameId": release_frame,
        "arrivalFrameId": last_frame if last_frame > release_frame else None,
        "eventSource": "derived-window-boundaries",
    }
    for frame in play["frames"]:
        for entity in frame["entities"]:
            source = players[entity["id"]]
            entity["role"] = _text(source.get("player_role"))
            predicted = (source.get("player_to_predict") or "").strip().lower()
            entity["playerToPredict"] = predicted == "true" if predicted in {"true", "false"} else None
    files = [SUPPLEMENTARY_FILE, input_file]
    if output_file and output_rows:
        files.append(output_file)
    play["provenance"]["files"] = files
    play["flightForecast"] = flight.release_states(play)
    play["accelerationForecast"] = flight.release_states(play, flight.ACCELERATION)
    return play


def _tracking_row(row: dict[str, str], offense: str | None, defense: str | None) -> dict[str, str]:
    """A pass-window input row in the column names ``tracking.build_play`` reads."""
    side = (row.get("player_side") or "").lower()
    club = offense if side == "offense" else defense if side == "defense" else None
    return {
        "gameId": row["game_id"],
        "playId": row["play_id"],
        "nflId": row["nfl_id"],
        "displayName": row.get("player_name", ""),
        "frameId": row["frame_id"],
        "club": club or side or "unknown",
        "playDirection": row.get("play_direction", ""),
        "x": row["x"],
        "y": row["y"],
        "s": row.get("s", ""),
        "a": row.get("a", ""),
        "dir": row.get("dir", ""),
        "o": row.get("o", ""),
    }


def _tracking_context(supplementary: dict[str, str], first_input: dict[str, str]) -> dict[str, str]:
    """Supplementary play context in the column names ``tracking.build_play`` reads."""
    return {
        "possessionTeam": supplementary.get("possession_team", ""),
        "defensiveTeam": supplementary.get("defensive_team", ""),
        "quarter": supplementary.get("quarter", ""),
        "down": supplementary.get("down", ""),
        "yardsToGo": supplementary.get("yards_to_go", ""),
        "yardsGained": supplementary.get("yards_gained", ""),
        "absoluteYardlineNumber": first_input.get("absolute_yardline_number", ""),
        "playDescription": supplementary.get("play_description", ""),
    }


def _ball_landing(row: dict[str, str], direction: str) -> dict[str, float] | None:
    x, y = _float(row.get("ball_land_x")), _float(row.get("ball_land_y"))
    if x is None or y is None or not math.isfinite(x) or not math.isfinite(y):
        return None
    if direction == "left":
        x, y = FIELD_LENGTH - x, FIELD_WIDTH - y
    return {"x": round(x, 3), "y": round(y, 3)}


def _game_row(context: dict[str, str]) -> tuple[Any, ...]:
    return (
        context["game_id"],
        _integer(context.get("season")),
        _integer(context.get("week")),
        _text(context.get("game_date")),
        _text(context.get("home_team_abbr")),
        _text(context.get("visitor_team_abbr")),
    )


def _play_row(context: dict[str, str]) -> tuple[Any, ...]:
    pass_result = _text(context.get("pass_result"))
    description = _text(context.get("play_description")) or "Tracking play"
    raw = {name: value for name, value in context.items() if name != "absolute_yardline_number"}
    return (
        context["game_id"],
        context["play_id"],
        _text(context.get("possession_team")),
        _text(context.get("defensive_team")),
        _integer(context.get("quarter")),
        _integer(context.get("down")),
        _float(context.get("yards_to_go")),
        _float(context.get("yards_gained")),
        _float(context.get("absolute_yardline_number")),
        "pass" if pass_result or _text(context.get("dropback_type")) else "other",
        description,
        pass_result,
        json.dumps(raw, separators=(",", ":"), sort_keys=True),
    )


def _supplementary(path: Path, only: Key | None = None) -> dict[Key, dict[str, str]]:
    return {
        key: row
        for row in _rows(path)
        if (key := (row["game_id"], row["play_id"])) == only or only is None
    }


def _grouped(rows: Iterable[dict[str, str]]) -> dict[Key, list[dict[str, str]]]:
    grouped: dict[Key, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row["game_id"], row["play_id"])].append(row)
    return grouped


def _contiguous(rows: Iterable[dict[str, str]]) -> Iterator[tuple[Key, list[dict[str, str]]]]:
    """Each play's block of rows, in file order, holding only one play in memory at a time."""
    key: Key | None = None
    block: list[dict[str, str]] = []
    for row in rows:
        row_key = (row["game_id"], row["play_id"])
        if row_key != key and block:
            yield key, block  # type: ignore[misc]
            block = []
        key = row_key
        block.append(row)
    if block:
        yield key, block  # type: ignore[misc]


def _play_rows(path: Path, key: Key) -> list[dict[str, str]]:
    """Rows for one play, stopping once its contiguous block has been read."""
    selected: list[dict[str, str]] = []
    for row in _rows(path):
        if (row["game_id"], row["play_id"]) == key:
            selected.append(row)
        elif selected:
            break
    return selected


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def _matching(directory: Path, pattern: re.Pattern[str]) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted((path for path in directory.iterdir() if pattern.search(path.name)), key=lambda path: path.name)


def _season_week(path: Path, pattern: re.Pattern[str]) -> tuple[int, int]:
    match = pattern.search(path.name)
    assert match is not None
    return int(match.group(1)), int(match.group(2))


def _header_errors(path: Path, required: set[str]) -> list[str]:
    if not path.is_file():
        return [f"Missing required {path.name}"]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        headers = set(next(csv.reader(handle), []))
    missing = sorted(required - headers)
    return [f"{path.name} is missing required columns: {', '.join(missing)}"] if missing else []


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped and stripped.lower() not in {"na", "nan", "none", "null"} else None


def _integer(value: str | None) -> int | None:
    text = _text(value)
    return int(float(text)) if text is not None else None


def _float(value: str | None) -> float | None:
    text = _text(value)
    return float(text) if text is not None else None
