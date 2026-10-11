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

from .tracking import extract_play

CATALOG_SCHEMA_VERSION = 1
TRACKING_FILE_PATTERN = re.compile(r"tracking_week_(\d+)\.csv$")

REQUIRED_HEADERS = {
    "games": {"gameId", "season", "week", "homeTeamAbbr", "visitorTeamAbbr"},
    "plays": {
        "gameId",
        "playId",
        "possessionTeam",
        "defensiveTeam",
        "quarter",
        "down",
        "yardsToGo",
        "playDescription",
    },
    "players": {"nflId", "displayName", "position"},
    "tracking": {
        "gameId",
        "playId",
        "nflId",
        "frameId",
        "club",
        "playDirection",
        "x",
        "y",
        "s",
        "a",
        "o",
        "dir",
        "event",
    },
}


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


@dataclass(frozen=True)
class _SourceFile:
    path: Path
    role: str
    week: int | None
    size_bytes: int
    sha256: str


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
                )

            try:
                games = tuple(self._game_rows(discovered["games"]))
                plays = tuple(self._play_rows(discovered["plays"]))
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

            known_game_ids = {row[0] for row in games}
            unmatched_plays = sum(1 for row in plays if row[0] not in known_game_ids)
            if unmatched_plays:
                warnings.append(f"{unmatched_plays} plays reference a game absent from games.csv")

            catalog_weeks = {row[2] for row in games if row[2] is not None}
            tracking_weeks = {item.week for item in tracking_files}
            missing_weeks = sorted(catalog_weeks - tracking_weeks)
            if missing_weeks:
                warnings.append(
                    "No tracking CSV was found for catalog weeks: "
                    + ", ".join(str(week) for week in missing_weeks)
                )
            if discovered.get("player_play") is None:
                warnings.append("player_play.csv is unavailable; player-play attributes were not cataloged")

            connection.execute("BEGIN TRANSACTION")
            try:
                for table in ("catalog_metadata", "source_files", "tracking_files", "games", "plays", "players"):
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
                    "INSERT INTO source_files VALUES (?, ?, ?, ?, ?)",
                    [
                        (str(item.path), item.role, item.size_bytes, item.sha256, item.week)
                        for item in source_files
                    ],
                )
                connection.executemany(
                    "INSERT INTO tracking_files VALUES (?, ?)",
                    [(item.week, str(item.path)) for item in tracking_files],
                )

                metadata = {
                    "schema_version": str(CATALOG_SCHEMA_VERSION),
                    "source_root": str(source_root),
                    "fingerprint": fingerprint,
                    "ingested_at": ingested_at,
                    "games_path": str(discovered["games"]),
                    "plays_path": str(discovered["plays"]),
                    "players_path": str(discovered["players"]),
                    "warnings": json.dumps(warnings),
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

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        connection = self._connect_existing()
        try:
            self._require_ready(connection)
            total = connection.execute(
                f"SELECT COUNT(*) FROM plays p JOIN games g USING (game_id){where}",
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                "SELECT p.game_id, p.play_id, g.season, g.week, g.game_date, "
                "p.offense, p.defense, p.quarter, p.down, p.yards_to_go, "
                "p.yards_gained, p.play_type, p.description "
                f"FROM plays p JOIN games g USING (game_id){where} "
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
                "SELECT g.week, tf.path "
                "FROM plays p JOIN games g USING (game_id) "
                "LEFT JOIN tracking_files tf ON tf.week = g.week "
                "WHERE p.game_id = ? AND p.play_id = ?",
                [game_key, play_key],
            ).fetchone()
            if row is None:
                raise CatalogNotFoundError(f"Play gameId={game_key}, playId={play_key} is not cataloged")
            week, tracking_path = row
            if tracking_path is None:
                raise CatalogNotFoundError(f"No tracking CSV is cataloged for week {week}")
            metadata = self._metadata(connection)
        finally:
            connection.close()

        play = extract_play(
            tracking_path,
            game_key,
            play_key,
            plays_path=metadata["plays_path"],
            players_path=metadata["players_path"],
        )
        play["source"]["releaseFingerprint"] = metadata["fingerprint"]
        play["source"]["catalogSchemaVersion"] = CATALOG_SCHEMA_VERSION
        return play

    def data_health(self) -> DataHealth:
        if not self.database_path.exists():
            return DataHealth(False, CATALOG_SCHEMA_VERSION, None, None, None, 0, 0, 0, 0, ())
        connection = self._connect_existing()
        try:
            self._initialize_schema(connection)
            return self._data_health(connection)
        finally:
            connection.close()

    def _discover_release(self, source_root: Path) -> dict[str, Any]:
        if not source_root.is_dir():
            raise CatalogValidationError([f"Source directory does not exist: {source_root}"])

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

        tracking_paths = sorted(source_root.glob("tracking_week_*.csv"), key=lambda path: path.name)
        if not tracking_paths:
            errors.append(f"No tracking_week_*.csv files found in {source_root}")
        seen_weeks: set[int] = set()
        for path in tracking_paths:
            week = self._tracking_week(path)
            if week is None:
                errors.append(f"Tracking filename does not include a valid week: {path.name}")
            elif week in seen_weeks:
                errors.append(f"More than one tracking CSV claims week {week}")
            else:
                seen_weeks.add(week)
            errors.extend(self._header_errors(path, REQUIRED_HEADERS["tracking"]))
        if errors:
            raise CatalogValidationError(errors)

        discovered["tracking"] = tracking_paths
        return discovered

    @staticmethod
    def _header_errors(path: Path, required: set[str]) -> list[str]:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            headers = set(next(csv.reader(handle), []))
        missing = sorted(required - headers)
        return [f"{path.name} is missing required columns: {', '.join(missing)}"] if missing else []

    def _fingerprint(self, discovered: dict[str, Any]) -> tuple[tuple[_SourceFile, ...], str]:
        paths: list[tuple[Path, str, int | None]] = [
            (discovered["games"], "games", None),
            (discovered["plays"], "plays", None),
            (discovered["players"], "players", None),
        ]
        if discovered.get("player_play"):
            paths.append((discovered["player_play"], "player_play", None))
        paths.extend((path, "tracking", self._tracking_week(path)) for path in discovered["tracking"])

        files: list[_SourceFile] = []
        release_hash = hashlib.sha256()
        for path, role, week in paths:
            digest = self._sha256(path)
            size = path.stat().st_size
            release_hash.update(f"{path.name}\0{size}\0{digest}\n".encode())
            files.append(_SourceFile(path.resolve(), role, week, size, digest))
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
    def _play_rows(path: Path) -> Iterable[tuple[Any, ...]]:
        for row in _csv_rows(path):
            yield (
                row["gameId"],
                row["playId"],
                _text(row.get("possessionTeam")),
                _text(row.get("defensiveTeam")),
                _integer(row.get("quarter")),
                _integer(row.get("down")),
                _float(row.get("yardsToGo")),
                _float(row.get("yardsGained")),
                _float(row.get("absoluteYardlineNumber")),
                _play_type(row),
                _text(row.get("playDescription")) or "Tracking play",
                _text(row.get("passResult")),
                json.dumps(row, separators=(",", ":"), sort_keys=True),
            )

    @staticmethod
    def _player_rows(path: Path) -> Iterable[tuple[Any, ...]]:
        for row in _csv_rows(path):
            yield (
                row["nflId"],
                _text(row.get("displayName")),
                _text(row.get("position")),
                _text(row.get("height")),
                _integer(row.get("weight")),
                _text(row.get("collegeName")),
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
                week INTEGER
            );
            CREATE TABLE IF NOT EXISTS tracking_files (
                week INTEGER PRIMARY KEY,
                path VARCHAR NOT NULL
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
            CREATE INDEX IF NOT EXISTS plays_offense_idx ON plays(offense);
            CREATE INDEX IF NOT EXISTS plays_defense_idx ON plays(defense);
            CREATE INDEX IF NOT EXISTS games_season_week_idx ON games(season, week);
            """
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
        )


def _csv_rows(path: Path) -> Iterable[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _integer(value: str | None) -> int | None:
    text = _text(value)
    return int(float(text)) if text is not None and not _is_missing_number(text) else None


def _float(value: str | None) -> float | None:
    text = _text(value)
    return float(text) if text is not None and not _is_missing_number(text) else None


def _is_missing_number(value: str) -> bool:
    return value.lower() in {"na", "nan", "none", "null"}


def _play_type(row: dict[str, str]) -> str:
    if _text(row.get("passResult")) or _text(row.get("dropbackType")):
        return "pass"
    if _text(row.get("rushLocationType")) or _text(row.get("rushLocation")):
        return "rush"
    description = (row.get("playDescription") or "").lower()
    if " pass" in description or description.startswith("pass"):
        return "pass"
    if " rush" in description or " left end" in description or " right end" in description:
        return "rush"
    return "other"
