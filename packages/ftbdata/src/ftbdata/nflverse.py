"""nflverse play-by-play enrichment for a tracking catalog.

nflverse rows are stored in their own tables and joined to tracking plays at
query time. That keeps enrichment independent of Big Data Bowl ingestion order
(re-ingesting tracking never discards it) and means a tracking play is never
removed because enrichment is missing: it is reported as ``unmatched`` or
``unavailable`` instead.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

PBP_FILE_PATTERN = re.compile(r"play_by_play_(\d{4})\.parquet$")
PBP_DOWNLOAD_HINT = (
    "Download play_by_play_<season>.parquet from "
    "https://github.com/nflverse/nflverse-data/releases/tag/pbp"
)

# Join keys. Big Data Bowl gameId is nflverse old_game_id; playId is play_id.
REQUIRED_COLUMNS = ("game_id", "old_game_id", "play_id", "season", "week")

# Join statuses, in the order they are reported.
JOIN_STATUSES = ("matched", "conflicting", "unmatched", "unavailable")


@dataclass(frozen=True)
class Field:
    """One nflverse column kept in the catalog."""

    name: str
    source: str
    sql_type: str


# `name` is the catalog column (and, in camelCase, the API key); `source` is the
# nflverse column. Formation and personnel only exist in newer seasons, so every
# field other than the join keys may be absent from a given file.
FIELDS: tuple[Field, ...] = (
    Field("season", "season", "INTEGER"),
    Field("week", "week", "INTEGER"),
    Field("season_type", "season_type", "VARCHAR"),
    Field("nflverse_game_id", "game_id", "VARCHAR"),
    Field("play_type", "play_type", "VARCHAR"),
    Field("description", "desc", "VARCHAR"),
    Field("quarter", "qtr", "INTEGER"),
    Field("clock", "time", "VARCHAR"),
    Field("half_seconds_remaining", "half_seconds_remaining", "DOUBLE"),
    Field("game_seconds_remaining", "game_seconds_remaining", "DOUBLE"),
    Field("down", "down", "INTEGER"),
    Field("yards_to_go", "ydstogo", "DOUBLE"),
    Field("yardline_100", "yardline_100", "DOUBLE"),
    Field("offense", "posteam", "VARCHAR"),
    Field("defense", "defteam", "VARCHAR"),
    Field("offense_score", "posteam_score", "DOUBLE"),
    Field("defense_score", "defteam_score", "DOUBLE"),
    Field("epa", "epa", "DOUBLE"),
    Field("wpa", "wpa", "DOUBLE"),
    Field("win_probability", "wp", "DOUBLE"),
    Field("yards_gained", "yards_gained", "DOUBLE"),
    Field("air_yards", "air_yards", "DOUBLE"),
    Field("yards_after_catch", "yards_after_catch", "DOUBLE"),
    Field("is_pass", "pass", "BOOLEAN"),
    Field("is_rush", "rush", "BOOLEAN"),
    Field("is_sack", "sack", "BOOLEAN"),
    Field("is_complete_pass", "complete_pass", "BOOLEAN"),
    Field("is_touchdown", "touchdown", "BOOLEAN"),
    Field("is_interception", "interception", "BOOLEAN"),
    Field("is_penalty", "penalty", "BOOLEAN"),
    Field("penalty_type", "penalty_type", "VARCHAR"),
    Field("penalty_yards", "penalty_yards", "DOUBLE"),
    Field("offense_formation", "offense_formation", "VARCHAR"),
    Field("offense_personnel", "offense_personnel", "VARCHAR"),
    Field("defense_personnel", "defense_personnel", "VARCHAR"),
    Field("defenders_in_box", "defenders_in_box", "INTEGER"),
)
FIELD_NAMES = tuple(field.name for field in FIELDS)

SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS nflverse_sources (
        season INTEGER PRIMARY KEY,
        path VARCHAR NOT NULL,
        size_bytes BIGINT NOT NULL,
        sha256 VARCHAR NOT NULL,
        plays INTEGER NOT NULL,
        unavailable_fields VARCHAR NOT NULL,
        ingested_at VARCHAR NOT NULL
    )
    """,
    "CREATE TABLE IF NOT EXISTS nflverse_plays ("
    "old_game_id VARCHAR NOT NULL, play_id VARCHAR NOT NULL, "
    + ", ".join(f"{field.name} {field.sql_type}" for field in FIELDS)
    + ", PRIMARY KEY (old_game_id, play_id))",
)

# A tracking play (alias ``p``, game ``g``) joined to its nflverse row (``n``)
# and the source file loaded for its season (``ns``). The season is part of the
# key so that identifiers reused across seasons can never cross-match.
JOIN_SQL = (
    "LEFT JOIN nflverse_plays n ON n.old_game_id = p.game_id AND n.play_id = p.play_id AND n.season = g.season "
    "LEFT JOIN nflverse_sources ns ON ns.season = g.season"
)

# Quarter and down are compared, but team codes are not: legacy Big Data Bowl
# releases use abbreviations (ARZ, BLT, CLV, HST) that nflverse has renamed.
CONFLICT_SQL = (
    "((p.quarter IS NOT NULL AND n.quarter IS NOT NULL AND p.quarter <> n.quarter) "
    "OR (p.down > 0 AND n.down IS NOT NULL AND p.down <> n.down))"
)

STATUS_SQL = (
    "CASE WHEN n.play_id IS NOT NULL "
    f"THEN CASE WHEN {CONFLICT_SQL} THEN 'conflicting' ELSE 'matched' END "
    "WHEN ns.season IS NOT NULL THEN 'unmatched' ELSE 'unavailable' END"
)


@dataclass(frozen=True)
class PbpFile:
    path: Path
    season: int
    size_bytes: int
    sha256: str
    plays: int
    unavailable_fields: tuple[str, ...]


@dataclass(frozen=True)
class EnrichmentReport:
    source_root: str
    fingerprint: str
    ingested_at: str
    seasons: tuple[int, ...]
    plays: int
    warnings: tuple[str, ...]
    coverage: "JoinCoverage"
    reused: bool = False


@dataclass(frozen=True)
class JoinCount:
    plays: int = 0
    matched: int = 0
    conflicting: int = 0
    unmatched: int = 0
    unavailable: int = 0
    # Share of plays whose season is loaded that joined consistently; None when no season is loaded.
    matched_rate: float | None = None

    @classmethod
    def from_statuses(cls, totals: dict[str, int]) -> "JoinCount":
        plays = sum(totals.values())
        eligible = plays - totals["unavailable"]
        return cls(plays=plays, **totals, matched_rate=totals["matched"] / eligible if eligible else None)


@dataclass(frozen=True)
class SeasonCoverage:
    season: int | None
    counts: JoinCount
    unavailable_fields: tuple[str, ...]


@dataclass(frozen=True)
class WeekCoverage:
    season: int | None
    week: int | None
    counts: JoinCount


@dataclass(frozen=True)
class JoinCoverage:
    """Measured join between catalog tracking plays and loaded nflverse seasons."""

    loaded: bool
    overall: JoinCount
    seasons: tuple[SeasonCoverage, ...] = ()
    weeks: tuple[WeekCoverage, ...] = ()


def discover_pbp_files(source_root: Path) -> list[tuple[int, Path]]:
    if not source_root.is_dir():
        raise FileNotFoundError(f"nflverse directory does not exist: {source_root}")
    found = sorted(
        (int(match.group(1)), path)
        for path in source_root.iterdir()
        if path.is_file() and (match := PBP_FILE_PATTERN.search(path.name))
    )
    seasons = [season for season, _ in found]
    duplicates = sorted({season for season in seasons if seasons.count(season) > 1})
    if duplicates:
        raise ValueError(f"More than one play-by-play file for season(s): {duplicates}")
    return found


def inspect_pbp_file(connection: duckdb.DuckDBPyConnection, season: int, path: Path) -> tuple[int, tuple[str, ...], list[str]]:
    """Return (rows, unavailable field names, errors) for one play-by-play Parquet file."""
    try:
        columns = {
            row[0] for row in connection.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
        }
    except duckdb.Error as error:
        return 0, (), [f"{path.name} is not a readable Parquet file: {error}"]

    errors: list[str] = []
    missing_keys = [column for column in REQUIRED_COLUMNS if column not in columns]
    if missing_keys:
        errors.append(f"{path.name} is missing required column(s): {', '.join(missing_keys)}")
        return 0, (), errors

    rows = connection.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    file_seasons = {
        row[0] for row in connection.execute("SELECT DISTINCT season FROM read_parquet(?)", [str(path)]).fetchall()
    }
    if file_seasons != {season}:
        errors.append(f"{path.name} contains season(s) {sorted(s for s in file_seasons if s is not None)}, not {season}")
    duplicates = connection.execute(
        "SELECT COUNT(*) FROM (SELECT old_game_id, play_id FROM read_parquet(?) "
        "WHERE old_game_id IS NOT NULL AND play_id IS NOT NULL "
        "GROUP BY 1, 2 HAVING COUNT(*) > 1)",
        [str(path)],
    ).fetchone()[0]
    if duplicates:
        errors.append(f"{path.name} has {duplicates} duplicated (old_game_id, play_id) keys")

    unavailable = tuple(field.name for field in FIELDS if field.source not in columns)
    return rows, unavailable, errors


def insert_pbp_file(connection: duckdb.DuckDBPyConnection, path: Path, unavailable: tuple[str, ...]) -> int:
    """Insert one validated file; return the number of rows skipped for missing keys."""
    expressions = [
        "CAST(old_game_id AS VARCHAR)",
        "CAST(CAST(play_id AS BIGINT) AS VARCHAR)",
    ]
    for field in FIELDS:
        if field.name in unavailable:
            expressions.append(f"CAST(NULL AS {field.sql_type})")
        else:
            expressions.append(f'TRY_CAST("{field.source}" AS {field.sql_type})')
    columns = ", ".join(("old_game_id", "play_id", *FIELD_NAMES))
    connection.execute(
        f"INSERT INTO nflverse_plays ({columns}) SELECT {', '.join(expressions)} "
        "FROM read_parquet(?) WHERE old_game_id IS NOT NULL AND play_id IS NOT NULL",
        [str(path)],
    )
    return connection.execute(
        "SELECT COUNT(*) FROM read_parquet(?) WHERE old_game_id IS NULL OR play_id IS NULL",
        [str(path)],
    ).fetchone()[0]


def camel_case(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.capitalize() for part in rest)


def play_enrichment(
    connection: duckdb.DuckDBPyConnection, game_id: str, play_id: str, fingerprint: str | None
) -> dict[str, Any]:
    """The ``enrichment.nflverse`` block served with a play."""
    selected = ", ".join(f"n.{name}" for name in FIELD_NAMES)
    row = connection.execute(
        f"SELECT {STATUS_SQL}, ns.path, ns.unavailable_fields, {selected} "
        f"FROM plays p JOIN games g USING (game_id) {JOIN_SQL} "
        "WHERE p.game_id = ? AND p.play_id = ?",
        [game_id, play_id],
    ).fetchone()
    status, source_path, unavailable_json, *values = row
    block: dict[str, Any] = {
        "status": status,
        "fingerprint": fingerprint if status in ("matched", "conflicting", "unmatched") else None,
        "sourceFile": Path(source_path).name if source_path else None,
        "unavailableFields": [camel_case(name) for name in _loads(unavailable_json)],
        "fields": None,
    }
    if status in ("matched", "conflicting"):
        block["fields"] = {camel_case(name): value for name, value in zip(FIELD_NAMES, values)}
    return block


def fingerprint(files: list[PbpFile]) -> str:
    """Deterministic over season, size, and content hash; independent of file location."""
    digest = hashlib.sha256()
    for item in sorted(files, key=lambda entry: entry.season):
        digest.update(f"{item.season}:{item.size_bytes}:{item.sha256}\n".encode())
    return digest.hexdigest()


def _loads(value: str | None) -> list[str]:
    return json.loads(value) if value else []
