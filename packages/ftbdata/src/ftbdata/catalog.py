from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

from . import nflverse, pass_window, quality
from .nflverse import EnrichmentReport, JoinCount, JoinCoverage, PbpFile, SeasonCoverage, WeekCoverage
from .quality import QualityReport
from .tracking import extract_play, read_lookup, scan_tracking_file

CATALOG_SCHEMA_VERSION = 5
TRACKING_FILE_PATTERN = re.compile(r"tracking_week_(\d+)\.csv$")
LEGACY_TRACKING_FILE_PATTERN = re.compile(r"tracking_gameId_(\d+)\.csv$")

REQUIRED_HEADERS = {
    "games": {"gameId", "season", "week", "homeTeamAbbr", "visitorTeamAbbr"},
    "plays": {
        "gameId",
        "playId",
        "possessionTeam",
        "quarter",
        "down",
        "yardsToGo",
        "playDescription",
    },
    "players": {"nflId"},
    "tracking": {
        "gameId",
        "playId",
        "nflId",
        "displayName",
        "jerseyNumber",
        "x",
        "y",
        "s",
        "dir",
        "event",
    },
}


_QUALITY_JOIN_SQL = "LEFT JOIN play_quality q ON q.game_id = p.game_id AND q.play_id = p.play_id"
_QUALITY_STATUS_SQL = "COALESCE(q.status, 'unassessed')"

# A play is searchable only when a tracking file backs it.
_TRACKED_SQL = (
    "EXISTS (SELECT 1 FROM tracking_files tf "
    "WHERE tf.game_id = p.game_id OR (tf.game_id IS NULL AND tf.week = g.week))"
)


class CatalogError(RuntimeError):
    """Base error raised by the tracking catalog."""


class CatalogNotFoundError(CatalogError):
    """A requested game, play, or tracking file is unavailable."""


class CatalogValidationError(CatalogError):
    """A source release cannot be cataloged safely."""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True)
class PlayFilters:
    season: int | None = None
    week: int | None = None
    offense: str | None = None
    defense: str | None = None
    down: int | None = None
    play_type: str | None = None
    text: str | None = None
    epa_min: float | None = None
    epa_max: float | None = None
    join_status: str | None = None
    quality_status: str | None = None


@dataclass(frozen=True)
class PlaySummary:
    game_id: str
    play_id: str
    season: int | None
    week: int | None
    game_date: str | None
    offense: str | None
    defense: str | None
    quarter: int | None
    down: int | None
    yards_to_go: float | None
    yards_gained: float | None
    play_type: str
    description: str
    epa: float | None = None
    join_status: str = "unavailable"
    quality_status: str = "unassessed"


@dataclass(frozen=True)
class PlayPage:
    items: tuple[PlaySummary, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True)
class IngestReport:
    source_root: str
    fingerprint: str
    ingested_at: str
    games: int
    plays: int
    players: int
    tracking_files: int
    warnings: tuple[str, ...]
    errors: tuple[str, ...] = ()
    reused: bool = False
    quality: QualityReport | None = None


@dataclass(frozen=True)
class DataHealth:
    ready: bool
    schema_version: int
    source_root: str | None
    fingerprint: str | None
    ingested_at: str | None
    games: int
    plays: int
    players: int
    tracking_files: int
    warnings: tuple[str, ...]
    join_coverage: JoinCoverage | None = None
    quality: QualityReport | None = None


@dataclass(frozen=True)
class _SourceFile:
    path: Path
    role: str
    week: int | None
    size_bytes: int
    sha256: str
    game_id: str | None = None


class TrackingCatalog:
    """Search and load a local Big Data Bowl release.

    The catalog stores only metadata and source-file locations. Tracking rows
    remain in their downloaded CSVs and are streamed when ``load_play`` is
    called, avoiding a second multi-gigabyte copy of a release.
    """

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)

    def ingest_release(self, source_directory: str | Path) -> IngestReport:
        source_root = Path(source_directory).expanduser().resolve()
        discovered = self._discover_release(source_root)
        source_files, fingerprint = self._fingerprint(discovered)
        ingested_at = datetime.now(timezone.utc).isoformat()
        warnings: list[str] = []

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            self._initialize_schema(connection)
            existing_metadata = self._metadata(connection)
            existing_fingerprint = existing_metadata.get("fingerprint")
            existing_schema = int(existing_metadata.get("schema_version", 0))
            if existing_fingerprint == fingerprint and existing_schema == CATALOG_SCHEMA_VERSION:
                health = self._data_health(connection)
                return IngestReport(
                    source_root=str(source_root),
                    fingerprint=fingerprint,
                    ingested_at=health.ingested_at or ingested_at,
                    games=health.games,
                    plays=health.plays,
                    players=health.players,
                    tracking_files=health.tracking_files,
                    warnings=health.warnings,
                    reused=True,
                    quality=health.quality,
                )

            if discovered["source_format"] == pass_window.TRACKING_FORMAT:
                games, plays, players, tracking_files, assessments = self._pass_window_rows(
                    discovered["release"], source_files, warnings
                )
            else:
                games, plays, players, tracking_files, assessments = self._csv_release_rows(
                    discovered, source_files, warnings
                )

            connection.execute("BEGIN TRANSACTION")
            try:
                for table in (
                    "catalog_metadata", "source_files", "tracking_files", "games", "plays", "players", "play_quality"
                ):
                    connection.execute(f"DELETE FROM {table}")

                connection.executemany(
                    "INSERT INTO games VALUES (?, ?, ?, ?, ?, ?)",
                    games,
                )
                connection.executemany(
                    "INSERT INTO plays VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    plays,
                )
                connection.executemany(
                    "INSERT INTO players VALUES (?, ?, ?, ?, ?, ?)",
                    players,
                )
                connection.executemany(
                    "INSERT INTO source_files VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (str(item.path), item.role, item.size_bytes, item.sha256, item.week, item.game_id)
                        for item in source_files
                    ],
                )
                connection.executemany(
                    "INSERT INTO tracking_files VALUES (?, ?, ?)",
                    [(str(item.path), item.week, item.game_id) for item in tracking_files],
                )
                connection.executemany("INSERT INTO play_quality VALUES (?, ?, ?, ?, ?, ?)", assessments)

                metadata = {
                    "schema_version": str(CATALOG_SCHEMA_VERSION),
                    "source_root": str(source_root),
                    "fingerprint": fingerprint,
                    "ingested_at": ingested_at,
                    **self._context_paths(discovered),
                    "source_format": discovered["source_format"],
                    "warnings": json.dumps(warnings),
                    "quality_version": str(quality.QUALITY_VERSION),
                    "status": "ready",
                }
                connection.executemany(
                    "INSERT INTO catalog_metadata VALUES (?, ?)",
                    list(metadata.items()),
                )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

            return IngestReport(
                source_root=str(source_root),
                fingerprint=fingerprint,
                ingested_at=ingested_at,
                games=len(games),
                plays=len(plays),
                players=len(players),
                tracking_files=len(tracking_files),
                warnings=tuple(warnings),
                quality=self._quality_report(connection),
            )
        finally:
            connection.close()

    def find_plays(
        self,
        filters: PlayFilters | None = None,
        *,
        page: int = 1,
        page_size: int = 50,
    ) -> PlayPage:
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= page_size <= 200:
            raise ValueError("page_size must be between 1 and 200")

        filters = filters or PlayFilters()
        clauses: list[str] = []
        parameters: list[Any] = []
        for column, value in (
            ("g.season", filters.season),
            ("g.week", filters.week),
            ("p.offense", filters.offense.upper() if filters.offense else None),
            ("p.defense", filters.defense.upper() if filters.defense else None),
            ("p.down", filters.down),
            ("p.play_type", filters.play_type.lower() if filters.play_type else None),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        if filters.text:
            clauses.append("LOWER(p.description) LIKE ?")
            parameters.append(f"%{filters.text.lower()}%")
        if filters.epa_min is not None:
            clauses.append("n.epa >= ?")
            parameters.append(filters.epa_min)
        if filters.epa_max is not None:
            clauses.append("n.epa <= ?")
            parameters.append(filters.epa_max)
        if filters.join_status is not None:
            if filters.join_status not in nflverse.JOIN_STATUSES:
                raise ValueError(f"join_status must be one of: {', '.join(nflverse.JOIN_STATUSES)}")
            clauses.append(f"({nflverse.STATUS_SQL}) = ?")
            parameters.append(filters.join_status)
        if filters.quality_status is not None:
            if filters.quality_status not in (*quality.PLAY_STATUSES, "unassessed"):
                raise ValueError(
                    f"quality_status must be one of: {', '.join((*quality.PLAY_STATUSES, 'unassessed'))}"
                )
            clauses.append(f"{_QUALITY_STATUS_SQL} = ?")
            parameters.append(filters.quality_status)
        clauses.append(_TRACKED_SQL)

        where = " WHERE " + " AND ".join(clauses)
        connection = self._connect_existing()
        try:
            self._require_ready(connection)
            total = connection.execute(
                f"SELECT COUNT(*) FROM plays p JOIN games g USING (game_id) {nflverse.JOIN_SQL} {_QUALITY_JOIN_SQL}{where}",
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT p.game_id, p.play_id, g.season, g.week, g.game_date, "
                "p.offense, p.defense, p.quarter, p.down, p.yards_to_go, "
                f"p.yards_gained, p.play_type, p.description, n.epa, {nflverse.STATUS_SQL}, {_QUALITY_STATUS_SQL} "
                f"FROM plays p JOIN games g USING (game_id) {nflverse.JOIN_SQL} {_QUALITY_JOIN_SQL}{where} "
                "ORDER BY g.season DESC, g.week, p.game_id, TRY_CAST(p.play_id AS BIGINT), p.play_id "
                "LIMIT ? OFFSET ?",
                [*parameters, page_size, (page - 1) * page_size],
            ).fetchall()
        finally:
            connection.close()

        return PlayPage(
            items=tuple(PlaySummary(*row) for row in rows),
            page=page,
            page_size=page_size,
            total=total,
        )

    def load_play(self, game_id: str | int, play_id: str | int) -> dict[str, Any]:
        game_key, play_key = str(game_id), str(play_id)
        connection = self._connect_existing()
        try:
            self._require_ready(connection)
            row = connection.execute(
                "SELECT g.week, g.season FROM plays p JOIN games g USING (game_id) "
                "WHERE p.game_id = ? AND p.play_id = ?",
                [game_key, play_key],
            ).fetchone()
            if row is None:
                raise CatalogNotFoundError(f"Play gameId={game_key}, playId={play_key} is not cataloged")
            week, season = row
            tracking_row = connection.execute(
                "SELECT path FROM tracking_files "
                "WHERE game_id = ? OR (game_id IS NULL AND week = ?) "
                "ORDER BY CASE WHEN game_id = ? THEN 0 ELSE 1 END LIMIT 1",
                [game_key, week, game_key],
            ).fetchone()
            tracking_path = tracking_row[0] if tracking_row else None
            if tracking_path is None:
                raise CatalogNotFoundError(f"No tracking CSV is cataloged for week {week}")
            metadata = self._metadata(connection)
            output_row = connection.execute(
                "SELECT path FROM source_files WHERE role = 'tracking-output' AND week = ?", [week]
            ).fetchone()
            enrichment = nflverse.play_enrichment(
                connection, game_key, play_key, self._nflverse_fingerprint(connection)
            )
        finally:
            connection.close()

        if metadata.get("source_format") == pass_window.TRACKING_FORMAT:
            week_files = pass_window.WeekFiles(
                season, week, Path(tracking_path), Path(output_row[0]) if output_row else None
            )
            play = pass_window.load_play(week_files, Path(metadata["supplementary_path"]), game_key, play_key)
            context_files: list[str] = []
        else:
            play = extract_play(
                tracking_path,
                game_key,
                play_key,
                plays_path=metadata["plays_path"],
                players_path=metadata["players_path"],
                games_path=metadata["games_path"],
            )
            context_files = [Path(metadata[key]).name for key in ("games_path", "plays_path", "players_path")]
        play["source"]["releaseFingerprint"] = metadata["fingerprint"]
        play["source"]["catalogSchemaVersion"] = CATALOG_SCHEMA_VERSION
        play["enrichment"] = {"nflverse": enrichment}
        release = Path(metadata["source_root"])
        provenance = play["provenance"]
        provenance["release"] = {
            "name": release.name,
            "competitionYear": _competition_year(release.name),
            "season": season,
            "fingerprint": metadata["fingerprint"],
            "ingestedAt": metadata["ingested_at"],
        }
        provenance["files"] = context_files + provenance["files"]
        provenance["nflverse"] = {"status": enrichment["status"], "fingerprint": enrichment["fingerprint"]}
        return play

    def ingest_nflverse(self, source_directory: str | Path) -> EnrichmentReport:
        """Load nflverse play-by-play seasons and measure how they join to tracking plays."""
        source_root = Path(source_directory).expanduser().resolve()
        try:
            found = nflverse.discover_pbp_files(source_root)
        except (FileNotFoundError, ValueError) as error:
            raise CatalogValidationError([str(error)]) from error
        if not found:
            raise CatalogValidationError([
                f"No play_by_play_<season>.parquet files found in {source_root}. {nflverse.PBP_DOWNLOAD_HINT}"
            ])

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = self._connect()
        try:
            self._initialize_schema(connection)
            inspected: list[tuple[int, Path, int, tuple[str, ...]]] = []
            errors: list[str] = []
            for season, path in found:
                rows, unavailable, file_errors = nflverse.inspect_pbp_file(connection, season, path)
                errors.extend(file_errors)
                inspected.append((season, path, rows, unavailable))
            if errors:
                raise CatalogValidationError(errors)

            files = [
                PbpFile(path, season, path.stat().st_size, self._sha256(path), rows, unavailable)
                for season, path, rows, unavailable in inspected
            ]
            fingerprint = nflverse.fingerprint(files)
            if self._nflverse_fingerprint(connection) == fingerprint:
                return EnrichmentReport(
                    source_root=str(source_root),
                    fingerprint=fingerprint,
                    ingested_at=connection.execute("SELECT MAX(ingested_at) FROM nflverse_sources").fetchone()[0],
                    seasons=tuple(item.season for item in files),
                    plays=sum(item.plays for item in files),
                    warnings=tuple(self._nflverse_warnings(connection, files, {})),
                    coverage=self._join_coverage(connection),
                    reused=True,
                )

            ingested_at = datetime.now(timezone.utc).isoformat()
            skipped: dict[int, int] = {}
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute("DELETE FROM nflverse_plays")
                connection.execute("DELETE FROM nflverse_sources")
                for item in files:
                    skipped[item.season] = nflverse.insert_pbp_file(connection, item.path, item.unavailable_fields)
                    connection.execute(
                        "INSERT INTO nflverse_sources VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [
                            item.season,
                            str(item.path),
                            item.size_bytes,
                            item.sha256,
                            item.plays,
                            json.dumps(list(item.unavailable_fields)),
                            ingested_at,
                        ],
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

            return EnrichmentReport(
                source_root=str(source_root),
                fingerprint=fingerprint,
                ingested_at=ingested_at,
                seasons=tuple(item.season for item in files),
                plays=sum(item.plays - skipped[item.season] for item in files),
                warnings=tuple(self._nflverse_warnings(connection, files, skipped)),
                coverage=self._join_coverage(connection),
            )
        finally:
            connection.close()

    def quality_report(self) -> QualityReport:
        """Measured tracking quality by check, season, and week."""
        if not self.database_path.exists():
            return quality.summarize([], None)
        connection = self._connect_existing()
        try:
            self._initialize_schema(connection)
            return self._quality_report(connection)
        finally:
            connection.close()

    def play_quality(self, statuses: Iterable[str] = (quality.INCOMPLETE, quality.INVALID)) -> tuple[dict[str, Any], ...]:
        """Per-play findings for plays whose assessed status is in ``statuses``."""
        wanted = tuple(statuses)
        connection = self._connect_existing()
        try:
            self._require_ready(connection)
            rows = connection.execute(
                "SELECT q.game_id, q.play_id, g.season, g.week, q.status, q.errors, q.warnings, q.findings_json "
                "FROM play_quality q JOIN plays p ON p.game_id = q.game_id AND p.play_id = q.play_id "
                f"JOIN games g ON g.game_id = p.game_id WHERE {_TRACKED_SQL} "
                "ORDER BY g.season, g.week, q.game_id, TRY_CAST(q.play_id AS BIGINT), q.play_id"
            ).fetchall()
        finally:
            connection.close()
        return tuple(
            {
                "game_id": game_id,
                "play_id": play_id,
                "season": season,
                "week": week,
                "status": status,
                "errors": errors,
                "warnings": warnings,
                "findings": json.loads(findings),
            }
            for game_id, play_id, season, week, status, errors, warnings, findings in rows
            if status in wanted
        )

    def join_coverage(self) -> JoinCoverage:
        if not self.database_path.exists():
            return JoinCoverage(loaded=False, overall=JoinCount())
        connection = self._connect_existing()
        try:
            self._initialize_schema(connection)
            return self._join_coverage(connection)
        finally:
            connection.close()

    def data_health(self) -> DataHealth:
        if not self.database_path.exists():
            return DataHealth(False, CATALOG_SCHEMA_VERSION, None, None, None, 0, 0, 0, 0, ())
        connection = self._connect_existing()
        try:
            self._initialize_schema(connection)
            return self._data_health(connection)
        finally:
            connection.close()

    def _csv_release_rows(
        self, discovered: dict[str, Any], source_files: tuple[_SourceFile, ...], warnings: list[str]
    ) -> tuple[tuple[Any, ...], ...]:
        """Catalog rows and quality assessments for a release of games/plays/players CSVs."""
        try:
            all_games = tuple(self._game_rows(discovered["games"]))
            tracked_game_ids = {item.game_id for item in source_files if item.game_id is not None}
            tracked_weeks = {item.week for item in source_files if item.role == "tracking" and item.week is not None}
            games = tuple(
                row
                for row in all_games
                if row[0] in tracked_game_ids or row[2] in tracked_weeks
            )
            teams_by_game = {row[0]: (row[4], row[5]) for row in games}
            plays = tuple(
                row for row in self._play_rows(discovered["plays"], teams_by_game) if row[0] in teams_by_game
            )
            players = tuple(self._player_rows(discovered["players"]))
        except (KeyError, TypeError, ValueError) as error:
            raise CatalogValidationError([f"Could not parse release metadata: {error}"]) from error
        empty_sources = [
            name
            for name, rows in (("games.csv", games), ("plays.csv", plays), ("players.csv", players))
            if not rows
        ]
        if empty_sources:
            raise CatalogValidationError(
                [f"Source files contain no data rows: {', '.join(empty_sources)}"]
            )
        tracking_files = tuple(item for item in source_files if item.role == "tracking")

        omitted_games = len(all_games) - len(games)
        if omitted_games:
            warnings.append(
                f"{omitted_games} games without a matching tracking file were omitted from the catalog"
            )

        known_game_ids = {row[0] for row in games}
        unmatched_plays = sum(1 for row in plays if row[0] not in known_game_ids)
        if unmatched_plays:
            warnings.append(f"{unmatched_plays} plays reference a game absent from games.csv")

        catalog_weeks = {row[2] for row in games if row[2] is not None}
        tracking_weeks = {item.week for item in tracking_files}
        missing_weeks = sorted(catalog_weeks - tracking_weeks) if discovered["source_format"] == "weekly" else []
        if missing_weeks:
            warnings.append(
                "No tracking CSV was found for catalog weeks: "
                + ", ".join(str(week) for week in missing_weeks)
            )
        if discovered.get("player_play") is None:
            warnings.append("player_play.csv is unavailable; player-play attributes were not cataloged")
        if discovered["source_format"] == "legacy-game":
            warnings.append(
                "Legacy game-level tracking omits acceleration, body orientation, and source play direction; "
                "direction is inferred from the line of scrimmage when possible"
            )

        assessments = self._assess_release(discovered, games, plays, tracking_files)
        return games, plays, players, tracking_files, tuple(assessments)

    def _pass_window_rows(
        self, release: pass_window.Release, source_files: tuple[_SourceFile, ...], warnings: list[str]
    ) -> tuple[tuple[Any, ...], ...]:
        """Catalog rows and quality assessments for a pass-window release."""
        try:
            rows = pass_window.catalog_rows(release)
        except (OSError, UnicodeDecodeError, csv.Error, KeyError, ValueError) as error:
            raise CatalogValidationError([f"Could not read pass-window release: {error}"]) from error
        if not rows.plays:
            raise CatalogValidationError(["No tracked play in the input files appears in supplementary_data.csv"])
        warnings.extend(rows.warnings)
        tracking_files = tuple(item for item in source_files if item.role == "tracking")
        return (
            tuple(rows.games),
            tuple(rows.plays),
            tuple(rows.players),
            tracking_files,
            tuple(self._quality_rows(rows.plays, rows.validations)),
        )

    @staticmethod
    def _assess_release(
        discovered: dict[str, Any],
        games: tuple[tuple[Any, ...], ...],
        plays: tuple[tuple[Any, ...], ...],
        tracking_files: tuple[_SourceFile, ...],
    ) -> list[tuple[Any, ...]]:
        """Stream every tracking file once and assess each cataloged play with ``quality.assess_play``."""
        play_lookup = read_lookup(discovered["plays"], ("gameId", "playId"))
        game_lookup = read_lookup(discovered["games"], ("gameId",))
        player_lookup = read_lookup(discovered["players"], ("nflId",))
        week_by_game = {row[0]: row[2] for row in games}

        validations: dict[tuple[str, str], dict[str, Any]] = {}
        for item in tracking_files:
            selected = {
                (row[0], row[1]): play_lookup[(row[0], row[1])]
                for row in plays
                if (row[0], row[1]) in play_lookup
                and (row[0] == item.game_id if item.game_id is not None else week_by_game.get(row[0]) == item.week)
            }
            try:
                for key, outcome in scan_tracking_file(
                    item.path, plays=selected, games=game_lookup, players=player_lookup
                ):
                    validations[key] = (
                        quality.failed_validation(outcome)
                        if isinstance(outcome, str)
                        else outcome["provenance"]["validation"]
                    )
            except (OSError, UnicodeDecodeError, csv.Error) as error:
                raise CatalogValidationError([f"Could not read {item.path.name}: {error}"]) from error
            for key in selected:
                validations.setdefault(
                    key, quality.failed_validation(f"No tracking rows for this play in {item.path.name}")
                )

        return TrackingCatalog._quality_rows(plays, validations)

    @staticmethod
    def _quality_rows(
        plays: Iterable[tuple[Any, ...]], validations: dict[tuple[str, str], dict[str, Any]]
    ) -> list[tuple[Any, ...]]:
        return [
            (
                row[0],
                row[1],
                validation["status"],
                validation["errors"],
                validation["warnings"],
                json.dumps(quality.non_pass_checks(validation), separators=(",", ":")),
            )
            for row in plays
            if (validation := validations.get((row[0], row[1]))) is not None
        ]

    @staticmethod
    def _quality_report(connection: duckdb.DuckDBPyConnection) -> QualityReport:
        rows = connection.execute(
            "SELECT g.season, g.week, q.status, q.findings_json "
            "FROM play_quality q JOIN plays p ON p.game_id = q.game_id AND p.play_id = q.play_id "
            f"JOIN games g ON g.game_id = p.game_id WHERE {_TRACKED_SQL}"
        ).fetchall()
        assessed_at = connection.execute(
            "SELECT value FROM catalog_metadata WHERE key = 'ingested_at'"
        ).fetchone()
        return quality.summarize(
            ((season, week, status, json.loads(findings)) for season, week, status, findings in rows),
            assessed_at[0] if assessed_at and rows else None,
        )

    def _discover_release(self, source_root: Path) -> dict[str, Any]:
        if not source_root.is_dir():
            raise CatalogValidationError([f"Source directory does not exist: {source_root}"])
        if pass_window.is_release(source_root):
            release, errors = pass_window.discover(source_root)
            if errors:
                raise CatalogValidationError(errors)
            return {"source_format": pass_window.TRACKING_FORMAT, "release": release}

        discovered: dict[str, Any] = {
            "games": source_root / "games.csv",
            "plays": source_root / "plays.csv",
            "players": source_root / "players.csv",
            "player_play": source_root / "player_play.csv",
        }
        errors: list[str] = []
        for role in ("games", "plays", "players"):
            path = discovered[role]
            if path is None or not path.is_file():
                errors.append(f"Missing required {role}.csv in {source_root}")
            else:
                errors.extend(self._header_errors(path, REQUIRED_HEADERS[role]))

        player_play = discovered["player_play"]
        if player_play is not None and not player_play.is_file():
            discovered["player_play"] = None

        weekly_tracking_paths = sorted(source_root.glob("tracking_week_*.csv"), key=lambda path: path.name)
        legacy_tracking_paths = sorted(source_root.glob("tracking_gameId_*.csv"), key=lambda path: path.name)
        tracking_paths = [*weekly_tracking_paths, *legacy_tracking_paths]
        if not tracking_paths:
            errors.append(
                f"No tracking_week_*.csv or tracking_gameId_*.csv files found in {source_root}"
            )
        seen_weeks: set[int] = set()
        seen_games: set[str] = set()
        for path in tracking_paths:
            week = self._tracking_week(path)
            game_id = self._tracking_game(path)
            if week is not None and week in seen_weeks:
                errors.append(f"More than one tracking CSV claims week {week}")
            elif week is not None:
                seen_weeks.add(week)
            elif game_id is not None and game_id in seen_games:
                errors.append(f"More than one tracking CSV claims game {game_id}")
            elif game_id is not None:
                seen_games.add(game_id)
            else:
                errors.append(f"Tracking filename has no valid week or game ID: {path.name}")
            errors.extend(self._header_errors(path, REQUIRED_HEADERS["tracking"]))
            headers = self._headers(path)
            if not ({"frameId", "frame.id"} & headers):
                errors.append(f"{path.name} is missing a frame identifier (frameId or frame.id)")
            if not ({"club", "team"} & headers):
                errors.append(f"{path.name} is missing a team identifier (club or team)")

        player_headers = self._headers(discovered["players"]) if discovered["players"].is_file() else set()
        if player_headers and not ({"displayName", "LastName"} & player_headers):
            errors.append("players.csv is missing player names (displayName or LastName)")
        if player_headers and not ({"position", "PositionAbbr"} & player_headers):
            errors.append("players.csv is missing player position (position or PositionAbbr)")
        if errors:
            raise CatalogValidationError(errors)

        discovered["tracking"] = tracking_paths
        discovered["source_format"] = "legacy-game" if legacy_tracking_paths else "weekly"
        return discovered

    @staticmethod
    def _context_paths(discovered: dict[str, Any]) -> dict[str, str]:
        """Metadata keys naming the files that hold game and play context."""
        if discovered["source_format"] == pass_window.TRACKING_FORMAT:
            return {"supplementary_path": str(discovered["release"].supplementary)}
        return {f"{role}_path": str(discovered[role]) for role in ("games", "plays", "players")}

    @staticmethod
    def _header_errors(path: Path, required: set[str]) -> list[str]:
        headers = TrackingCatalog._headers(path)
        missing = sorted(required - headers)
        return [f"{path.name} is missing required columns: {', '.join(missing)}"] if missing else []

    @staticmethod
    def _headers(path: Path) -> set[str]:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return set(next(csv.reader(handle), []))

    def _fingerprint(self, discovered: dict[str, Any]) -> tuple[tuple[_SourceFile, ...], str]:
        if discovered["source_format"] == pass_window.TRACKING_FORMAT:
            release: pass_window.Release = discovered["release"]
            paths: list[tuple[Path, str, int | None, str | None]] = [(release.supplementary, "supplementary", None, None)]
            for week in release.weeks:
                paths.append((week.input, "tracking", week.week, None))
                if week.output is not None:
                    paths.append((week.output, "tracking-output", week.week, None))
            return self._hash_files(paths)
        paths = [
            (discovered["games"], "games", None, None),
            (discovered["plays"], "plays", None, None),
            (discovered["players"], "players", None, None),
        ]
        if discovered.get("player_play"):
            paths.append((discovered["player_play"], "player_play", None, None))
        paths.extend(
            (path, "tracking", self._tracking_week(path), self._tracking_game(path))
            for path in discovered["tracking"]
        )
        return self._hash_files(paths)

    def _hash_files(
        self, paths: list[tuple[Path, str, int | None, str | None]]
    ) -> tuple[tuple[_SourceFile, ...], str]:
        files: list[_SourceFile] = []
        release_hash = hashlib.sha256()
        for path, role, week, game_id in paths:
            digest = self._sha256(path)
            size = path.stat().st_size
            release_hash.update(f"{path.name}\0{size}\0{digest}\n".encode())
            files.append(_SourceFile(path.resolve(), role, week, size, digest, game_id))
        return tuple(files), release_hash.hexdigest()

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _tracking_week(path: Path) -> int | None:
        match = TRACKING_FILE_PATTERN.search(path.name)
        return int(match.group(1)) if match else None

    @staticmethod
    def _tracking_game(path: Path) -> str | None:
        match = LEGACY_TRACKING_FILE_PATTERN.search(path.name)
        return match.group(1) if match else None

    @staticmethod
    def _game_rows(path: Path) -> Iterable[tuple[Any, ...]]:
        for row in _csv_rows(path):
            yield (
                row["gameId"],
                _integer(row.get("season")),
                _integer(row.get("week")),
                _text(row.get("gameDate")),
                _text(row.get("homeTeamAbbr")),
                _text(row.get("visitorTeamAbbr")),
            )

    @staticmethod
    def _play_rows(
        path: Path, teams_by_game: dict[str, tuple[str | None, str | None]]
    ) -> Iterable[tuple[Any, ...]]:
        for row in _csv_rows(path):
            game_id = row["gameId"]
            offense = _text(row.get("possessionTeam"))
            home, away = teams_by_game.get(game_id, (None, None))
            defense = _text(row.get("defensiveTeam"))
            if defense is None and offense is not None:
                defense = away if offense == home else home if offense == away else None
            yield (
                game_id,
                row["playId"],
                offense,
                defense,
                _integer(row.get("quarter")),
                _integer(row.get("down")),
                _float(row.get("yardsToGo")),
                _float(row.get("yardsGained") or row.get("PlayResult")),
                _float(row.get("absoluteYardlineNumber")),
                _play_type(row),
                _text(row.get("playDescription")) or "Tracking play",
                _text(row.get("passResult") or row.get("PassResult")),
                json.dumps(row, separators=(",", ":"), sort_keys=True),
            )

    @staticmethod
    def _player_rows(path: Path) -> Iterable[tuple[Any, ...]]:
        for row in _csv_rows(path):
            display_name = _text(row.get("displayName"))
            if display_name is None:
                display_name = " ".join(
                    part for part in (_text(row.get("FirstName")), _text(row.get("LastName"))) if part
                ) or None
            yield (
                row["nflId"],
                display_name,
                _text(row.get("position") or row.get("PositionAbbr")),
                _text(row.get("height") or row.get("Height")),
                _integer(row.get("weight") or row.get("Weight")),
                _text(row.get("collegeName") or row.get("College")),
            )

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.database_path))

    def _connect_existing(self) -> duckdb.DuckDBPyConnection:
        if not self.database_path.is_file():
            raise CatalogNotFoundError(f"Catalog database does not exist: {self.database_path}")
        return self._connect()

    @staticmethod
    def _initialize_schema(connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS catalog_metadata (
                key VARCHAR PRIMARY KEY,
                value VARCHAR NOT NULL
            );
            CREATE TABLE IF NOT EXISTS source_files (
                path VARCHAR PRIMARY KEY,
                role VARCHAR NOT NULL,
                size_bytes BIGINT NOT NULL,
                sha256 VARCHAR NOT NULL,
                week INTEGER,
                game_id VARCHAR
            );
            CREATE TABLE IF NOT EXISTS tracking_files (
                path VARCHAR PRIMARY KEY,
                week INTEGER,
                game_id VARCHAR
            );
            CREATE TABLE IF NOT EXISTS games (
                game_id VARCHAR PRIMARY KEY,
                season INTEGER,
                week INTEGER,
                game_date VARCHAR,
                home_team VARCHAR,
                away_team VARCHAR
            );
            CREATE TABLE IF NOT EXISTS plays (
                game_id VARCHAR,
                play_id VARCHAR,
                offense VARCHAR,
                defense VARCHAR,
                quarter INTEGER,
                down INTEGER,
                yards_to_go DOUBLE,
                yards_gained DOUBLE,
                absolute_yardline DOUBLE,
                play_type VARCHAR NOT NULL,
                description VARCHAR NOT NULL,
                pass_result VARCHAR,
                raw_json VARCHAR NOT NULL,
                PRIMARY KEY (game_id, play_id)
            );
            CREATE TABLE IF NOT EXISTS players (
                nfl_id VARCHAR PRIMARY KEY,
                display_name VARCHAR,
                position VARCHAR,
                height VARCHAR,
                weight INTEGER,
                college VARCHAR
            );
            CREATE TABLE IF NOT EXISTS play_quality (
                game_id VARCHAR,
                play_id VARCHAR,
                status VARCHAR NOT NULL,
                errors INTEGER NOT NULL,
                warnings INTEGER NOT NULL,
                findings_json VARCHAR NOT NULL,
                PRIMARY KEY (game_id, play_id)
            );
            CREATE INDEX IF NOT EXISTS plays_offense_idx ON plays(offense);
            CREATE INDEX IF NOT EXISTS plays_defense_idx ON plays(defense);
            CREATE INDEX IF NOT EXISTS games_season_week_idx ON games(season, week);
            """
        )
        for statement in nflverse.SCHEMA_SQL:
            connection.execute(statement)
        source_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('source_files')").fetchall()
        }
        if "game_id" not in source_columns:
            connection.execute("ALTER TABLE source_files ADD COLUMN game_id VARCHAR")
        tracking_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('tracking_files')").fetchall()
        }
        if "game_id" not in tracking_columns:
            connection.execute("ALTER TABLE tracking_files RENAME TO tracking_files_v1")
            connection.execute(
                "CREATE TABLE tracking_files (path VARCHAR PRIMARY KEY, week INTEGER, game_id VARCHAR)"
            )
            connection.execute(
                "INSERT INTO tracking_files(path, week, game_id) "
                "SELECT path, week, NULL FROM tracking_files_v1"
            )
            connection.execute("DROP TABLE tracking_files_v1")

    @staticmethod
    def _nflverse_fingerprint(connection: duckdb.DuckDBPyConnection) -> str | None:
        rows = connection.execute("SELECT season, size_bytes, sha256 FROM nflverse_sources").fetchall()
        if not rows:
            return None
        return nflverse.fingerprint([PbpFile(Path(), season, size, sha, 0, ()) for season, size, sha in rows])

    @classmethod
    def _nflverse_warnings(
        cls, connection: duckdb.DuckDBPyConnection, files: list[PbpFile], skipped: dict[int, int]
    ) -> list[str]:
        warnings: list[str] = []
        for item in files:
            if item.unavailable_fields:
                warnings.append(
                    f"{item.season} play-by-play lacks {len(item.unavailable_fields)} field(s): "
                    + ", ".join(item.unavailable_fields)
                )
            if skipped.get(item.season):
                warnings.append(
                    f"{skipped[item.season]} {item.season} rows had no game or play identifier and were skipped"
                )
        coverage = cls._join_coverage(connection)
        for season in coverage.seasons:
            if season.counts.unavailable:
                warnings.append(
                    f"{season.counts.unavailable} cataloged plays in season {season.season} have no nflverse season file"
                )
            if season.counts.unmatched:
                warnings.append(
                    f"{season.counts.unmatched} cataloged plays in season {season.season} are absent from nflverse"
                )
            if season.counts.conflicting:
                warnings.append(
                    f"{season.counts.conflicting} cataloged plays in season {season.season} joined to an nflverse "
                    "row whose quarter or down disagrees"
                )
        return warnings

    @staticmethod
    def _join_coverage(connection: duckdb.DuckDBPyConnection) -> JoinCoverage:
        rows = connection.execute(
            f"SELECT g.season, g.week, {nflverse.STATUS_SQL}, COUNT(*) "
            f"FROM plays p JOIN games g USING (game_id) {nflverse.JOIN_SQL} "
            f"WHERE {_TRACKED_SQL} GROUP BY ALL"
        ).fetchall()
        unavailable_fields = {
            season: tuple(json.loads(fields))
            for season, fields in connection.execute(
                "SELECT season, unavailable_fields FROM nflverse_sources"
            ).fetchall()
        }

        def counts(selected: Iterable[tuple[str, int]]) -> JoinCount:
            totals = {status: 0 for status in nflverse.JOIN_STATUSES}
            for status, count in selected:
                totals[status] += count
            return JoinCount.from_statuses(totals)

        by_week: dict[tuple[int | None, int | None], list[tuple[str, int]]] = {}
        by_season: dict[int | None, list[tuple[str, int]]] = {}
        for season, week, status, count in rows:
            by_week.setdefault((season, week), []).append((status, count))
            by_season.setdefault(season, []).append((status, count))

        def order(key: Any) -> tuple[bool, Any]:
            return (key is None, key)

        return JoinCoverage(
            loaded=bool(unavailable_fields),
            overall=counts((status, count) for _, _, status, count in rows),
            seasons=tuple(
                SeasonCoverage(season, counts(by_season[season]), unavailable_fields.get(season, ()))
                for season in sorted(by_season, key=order)
            ),
            weeks=tuple(
                WeekCoverage(season, week, counts(by_week[(season, week)]))
                for season, week in sorted(by_week, key=lambda key: (order(key[0]), order(key[1])))
            ),
        )

    @staticmethod
    def _metadata(connection: duckdb.DuckDBPyConnection) -> dict[str, str]:
        return dict(connection.execute("SELECT key, value FROM catalog_metadata").fetchall())

    @classmethod
    def _require_ready(cls, connection: duckdb.DuckDBPyConnection) -> None:
        try:
            metadata = cls._metadata(connection)
        except duckdb.CatalogException as error:
            raise CatalogNotFoundError("Catalog database has not been initialized") from error
        if metadata.get("status") != "ready":
            raise CatalogNotFoundError("Catalog database has not ingested a complete release")

    @classmethod
    def _data_health(cls, connection: duckdb.DuckDBPyConnection) -> DataHealth:
        metadata = cls._metadata(connection)
        ready = metadata.get("status") == "ready"
        count = lambda table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return DataHealth(
            ready=ready,
            schema_version=int(metadata.get("schema_version", CATALOG_SCHEMA_VERSION)),
            source_root=metadata.get("source_root"),
            fingerprint=metadata.get("fingerprint"),
            ingested_at=metadata.get("ingested_at"),
            games=count("games"),
            plays=count("plays"),
            players=count("players"),
            tracking_files=count("tracking_files"),
            warnings=tuple(json.loads(metadata.get("warnings", "[]"))),
            join_coverage=cls._join_coverage(connection),
            quality=cls._quality_report(connection),
        )


def _competition_year(release_name: str) -> int | None:
    match = re.search(r"big-data-bowl-(\d{4})", release_name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _csv_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped and not _is_missing_number(stripped) else None


def _integer(value: str | None) -> int | None:
    text = _text(value)
    return int(float(text)) if text is not None and not _is_missing_number(text) else None


def _float(value: str | None) -> float | None:
    text = _text(value)
    return float(text) if text is not None and not _is_missing_number(text) else None


def _is_missing_number(value: str) -> bool:
    return value.lower() in {"na", "nan", "none", "null"}


def _play_type(row: dict[str, str]) -> str:
    if _text(row.get("passResult") or row.get("PassResult")) or _text(row.get("dropbackType")):
        return "pass"
    if _text(row.get("rushLocationType")) or _text(row.get("rushLocation")):
        return "rush"
    description = (row.get("playDescription") or "").lower()
    if " pass" in description or description.startswith("pass"):
        return "pass"
    rush_phrases = (
        " rush",
        " up the middle",
        " left end",
        " right end",
        " left guard",
        " right guard",
        " left tackle",
        " right tackle",
    )
    if any(phrase in description for phrase in rush_phrases):
        return "rush"
    return "other"
