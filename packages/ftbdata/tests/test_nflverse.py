from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from ftbdata.api import create_app
from ftbdata.catalog import CatalogValidationError, PlayFilters, TrackingCatalog
from ftbdata.cli import main


class NflverseEnrichmentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        self.release = self.root / "release"
        self.pbp = self.root / "pbp"
        self.release.mkdir()
        self.pbp.mkdir()
        self.database = self.root / "football.duckdb"
        self._write_release(self.release)
        self.catalog = TrackingCatalog(self.database)
        self.catalog.ingest_release(self.release)

    def test_join_statuses_are_measured_and_no_play_is_dropped(self) -> None:
        # Play 10 agrees with nflverse, 11 joins but disagrees on down, 12 has no nflverse row.
        self._write_pbp(2022, [
            self._row(10, qtr=1, down=2, epa=0.8, formation="SHOTGUN"),
            self._row(11, qtr=1, down=3, epa=-1.2),
            self._row(99, qtr=4, down=1, epa=0.1),  # nflverse-only play
        ])

        report = self.catalog.ingest_nflverse(self.pbp)

        self.assertFalse(report.reused)
        self.assertEqual(report.seasons, (2022,))
        self.assertEqual(report.plays, 3)
        overall = report.coverage.overall
        self.assertEqual(
            (overall.plays, overall.matched, overall.conflicting, overall.unmatched, overall.unavailable),
            (3, 1, 1, 1, 0),
        )
        self.assertEqual(overall.matched_rate, 1 / 3)
        self.assertTrue(any("quarter or down disagrees" in warning for warning in report.warnings))
        self.assertTrue(any("absent from nflverse" in warning for warning in report.warnings))

        season = report.coverage.seasons[0]
        self.assertEqual(season.season, 2022)
        self.assertIn("offense_personnel", season.unavailable_fields)
        self.assertNotIn("offense_formation", season.unavailable_fields)
        week = report.coverage.weeks[0]
        self.assertEqual((week.season, week.week, week.counts.plays), (2022, 1, 3))

        # Every tracking play is still searchable, each with its own status.
        page = self.catalog.find_plays(page_size=10)
        self.assertEqual(page.total, 3)
        status = {item.play_id: (item.join_status, item.epa) for item in page.items}
        self.assertEqual(status, {"10": ("matched", 0.8), "11": ("conflicting", -1.2), "12": ("unmatched", None)})

        self.assertEqual(self.catalog.find_plays(PlayFilters(join_status="unmatched")).items[0].play_id, "12")
        self.assertEqual(self.catalog.find_plays(PlayFilters(epa_min=0.5)).total, 1)
        self.assertEqual(self.catalog.find_plays(PlayFilters(epa_max=0.0)).items[0].play_id, "11")
        with self.assertRaises(ValueError):
            self.catalog.find_plays(PlayFilters(join_status="bogus"))

        matched = self.catalog.load_play("100", "10")["enrichment"]["nflverse"]
        self.assertEqual(matched["status"], "matched")
        self.assertEqual(matched["sourceFile"], "play_by_play_2022.parquet")
        self.assertEqual(matched["fingerprint"], report.fingerprint)
        self.assertEqual(matched["fields"]["epa"], 0.8)
        self.assertEqual(matched["fields"]["offenseFormation"], "SHOTGUN")
        self.assertTrue(matched["fields"]["isPass"])
        self.assertIn("offensePersonnel", matched["unavailableFields"])
        self.assertNotIn("/", matched["sourceFile"])

        unmatched = self.catalog.load_play("100", "12")["enrichment"]["nflverse"]
        self.assertEqual(unmatched["status"], "unmatched")
        self.assertIsNone(unmatched["fields"])
        self.assertEqual(len(self.catalog.load_play("100", "12")["frames"]), 2)

    def test_plays_are_unavailable_until_their_season_is_loaded(self) -> None:
        before = self.catalog.data_health()
        self.assertFalse(before.join_coverage.loaded)
        self.assertEqual(before.join_coverage.overall.unavailable, 3)
        self.assertIsNone(before.join_coverage.overall.matched_rate)
        absent = self.catalog.load_play("100", "10")["enrichment"]["nflverse"]
        self.assertEqual((absent["status"], absent["fields"], absent["sourceFile"]), ("unavailable", None, None))

        self._write_pbp(2021, [self._row(10, season=2021, qtr=1, down=2, epa=0.8)])
        report = self.catalog.ingest_nflverse(self.pbp)

        self.assertEqual(report.coverage.overall.unavailable, 3)
        self.assertTrue(report.coverage.loaded)
        self.assertTrue(any("no nflverse season file" in warning for warning in report.warnings))
        self.assertEqual(self.catalog.find_plays().total, 3)

    def test_ingest_is_idempotent_and_survives_tracking_reingest(self) -> None:
        self._write_pbp(2022, [self._row(10, qtr=1, down=2, epa=0.8)])
        first = self.catalog.ingest_nflverse(self.pbp)
        repeated = self.catalog.ingest_nflverse(self.pbp)
        self.assertTrue(repeated.reused)
        self.assertEqual(repeated.fingerprint, first.fingerprint)
        self.assertEqual(repeated.ingested_at, first.ingested_at)
        self.assertEqual(self.database_row_count("nflverse_plays"), 1)

        # Changing tracking metadata rebuilds the catalog tables but not the enrichment.
        plays_path = self.release / "plays.csv"
        plays_path.write_text(plays_path.read_text().replace("Pass complete", "Pass completed"))
        self.assertFalse(self.catalog.ingest_release(self.release).reused)
        play = self.catalog.load_play("100", "10")["enrichment"]["nflverse"]
        self.assertEqual((play["status"], play["fields"]["epa"]), ("matched", 0.8))

        # Changing the nflverse file changes the fingerprint and replaces the rows.
        self._write_pbp(2022, [self._row(10, qtr=1, down=2, epa=0.9)])
        changed = self.catalog.ingest_nflverse(self.pbp)
        self.assertFalse(changed.reused)
        self.assertNotEqual(changed.fingerprint, first.fingerprint)
        self.assertEqual(self.catalog.load_play("100", "10")["enrichment"]["nflverse"]["fields"]["epa"], 0.9)

    def test_invalid_sources_fail_with_actionable_errors(self) -> None:
        with self.assertRaises(CatalogValidationError) as empty:
            self.catalog.ingest_nflverse(self.pbp)
        self.assertIn("play_by_play_<season>.parquet", empty.exception.errors[0])
        self.assertIn("github.com/nflverse", empty.exception.errors[0])

        with self.assertRaises(CatalogValidationError) as missing_directory:
            self.catalog.ingest_nflverse(self.root / "nope")
        self.assertIn("does not exist", missing_directory.exception.errors[0])

        (self.pbp / "play_by_play_2022.parquet").write_text("not parquet")
        with self.assertRaises(CatalogValidationError) as unreadable:
            self.catalog.ingest_nflverse(self.pbp)
        self.assertIn("not a readable Parquet file", unreadable.exception.errors[0])

        self._write_pbp(2022, [self._row(10, qtr=1, down=2, epa=0.8)], drop=("old_game_id",))
        with self.assertRaises(CatalogValidationError) as no_key:
            self.catalog.ingest_nflverse(self.pbp)
        self.assertIn("old_game_id", no_key.exception.errors[0])

        self._write_pbp(2022, [self._row(10, qtr=1, down=2, epa=0.8), self._row(10, qtr=1, down=2, epa=0.9)])
        with self.assertRaises(CatalogValidationError) as duplicated:
            self.catalog.ingest_nflverse(self.pbp)
        self.assertIn("duplicated", duplicated.exception.errors[0])

        self._write_pbp(2022, [self._row(10, season=2021, qtr=1, down=2, epa=0.8)])
        with self.assertRaises(CatalogValidationError) as wrong_season:
            self.catalog.ingest_nflverse(self.pbp)
        self.assertIn("not 2022", wrong_season.exception.errors[0])

        # A failed ingest leaves no partial enrichment behind.
        self.assertEqual(self.database_row_count("nflverse_plays"), 0)
        self.assertFalse(self.catalog.data_health().join_coverage.loaded)

    def test_rows_without_a_play_identifier_are_skipped_and_reported(self) -> None:
        self._write_pbp(2022, [
            self._row(10, qtr=1, down=2, epa=0.8),
            self._row(None, qtr=1, down=1, epa=0.0),
        ])
        report = self.catalog.ingest_nflverse(self.pbp)
        self.assertEqual(report.plays, 1)
        self.assertTrue(any("no game or play identifier" in warning for warning in report.warnings))

    def test_cli_and_api_expose_enrichment_without_source_paths(self) -> None:
        self._write_pbp(2022, [self._row(10, qtr=1, down=2, epa=0.8), self._row(11, qtr=1, down=3, epa=-1.2)])

        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(["ingest", "nflverse", "--input", str(self.pbp), "--database", str(self.database)])
        self.assertEqual(exit_code, 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["coverage"]["overall"]["matched"], 1)
        self.assertEqual(report["coverage"]["overall"]["matched_rate"], 1 / 3)

        output = io.StringIO()
        with redirect_stdout(output):
            main(["plays", "--database", str(self.database), "--join-status", "matched", "--epa-min", "0"])
        self.assertEqual([item["play_id"] for item in json.loads(output.getvalue())["items"]], ["10"])

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["ingest", "nflverse", "--input", str(self.root / "nope")]), 2)

        client = TestClient(create_app(self.database))
        health = client.get("/data-health").json()["nflverse"]
        self.assertTrue(health["loaded"])
        self.assertEqual(health["overall"]["unmatched"], 1)
        self.assertEqual(health["seasons"][0]["season"], 2022)
        self.assertIn("offensePersonnel", health["seasons"][0]["unavailableFields"])
        self.assertEqual(health["weeks"][0]["conflicting"], 1)

        plays = client.get("/plays", params={"join_status": "unmatched"}).json()
        self.assertEqual([item["playId"] for item in plays["items"]], ["12"])
        self.assertEqual(plays["items"][0]["joinStatus"], "unmatched")
        self.assertIsNone(plays["items"][0]["epa"])
        self.assertEqual(client.get("/plays", params={"epa_min": 0.5}).json()["items"][0]["epa"], 0.8)
        self.assertEqual(client.get("/plays", params={"join_status": "bogus"}).status_code, 422)

        play = client.get("/plays/100/10")
        self.assertEqual(play.json()["enrichment"]["nflverse"]["fields"]["epa"], 0.8)
        self.assertNotIn(str(self.root), play.text)
        self.assertNotIn(str(self.root), client.get("/data-health").text)

    def database_row_count(self, table: str) -> int:
        connection = duckdb.connect(str(self.database), read_only=True)
        try:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            connection.close()

    @staticmethod
    def _row(play_id: int | None, *, season: int = 2022, qtr: int, down: int, epa: float, formation: str | None = None) -> dict:
        return {
            "game_id": f"{season}_01_DEN_SEA",
            "old_game_id": "100",
            "play_id": None if play_id is None else float(play_id),
            "season": season,
            "week": 1,
            "season_type": "REG",
            "play_type": "pass",
            "desc": f"nflverse play {play_id}",
            "qtr": float(qtr),
            "time": "14:55",
            "down": float(down),
            "ydstogo": 10.0,
            "posteam": "SEA",
            "defteam": "DEN",
            "epa": epa,
            "wpa": 0.01,
            "pass": 1.0,
            "rush": 0.0,
            "yards_gained": 6.0,
            "offense_formation": formation,
        }

    def _write_pbp(self, season: int, rows: list[dict], drop: tuple[str, ...] = ()) -> None:
        """Write a play-by-play Parquet file with no formation columns unless a row supplies one."""
        for stale in self.pbp.glob("*.parquet"):
            stale.unlink()
        columns = [name for name in rows[0] if name not in drop]
        if all(row.get("offense_formation") is None for row in rows):
            columns.remove("offense_formation")
        types = {
            "play_id": "DOUBLE", "qtr": "DOUBLE", "down": "DOUBLE", "ydstogo": "DOUBLE", "epa": "DOUBLE",
            "wpa": "DOUBLE", "pass": "DOUBLE", "rush": "DOUBLE", "yards_gained": "DOUBLE",
            "season": "INTEGER", "week": "INTEGER",
        }
        connection = duckdb.connect()
        try:
            definition = ", ".join(f'"{name}" {types.get(name, "VARCHAR")}' for name in columns)
            connection.execute(f"CREATE TABLE pbp ({definition})")
            connection.executemany(
                f"INSERT INTO pbp VALUES ({', '.join('?' for _ in columns)})",
                [[row[name] for name in columns] for row in rows],
            )
            connection.execute(
                f"COPY pbp TO '{self.pbp / f'play_by_play_{season}.parquet'}' (FORMAT PARQUET)"
            )
        finally:
            connection.close()

    @staticmethod
    def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)

    def _write_release(self, root: Path) -> None:
        self._write(
            root / "games.csv",
            ["gameId", "season", "week", "gameDate", "homeTeamAbbr", "visitorTeamAbbr"],
            [["100", "2022", "1", "09/08/2022", "SEA", "DEN"]],
        )
        self._write(
            root / "plays.csv",
            [
                "gameId", "playId", "possessionTeam", "defensiveTeam", "quarter",
                "down", "yardsToGo", "yardsGained", "absoluteYardlineNumber",
                "playDescription", "passResult", "dropbackType", "rushLocationType",
            ],
            [
                ["100", "10", "SEA", "DEN", "1", "2", "8", "14", "80", "Pass complete to the left", "C", "TRADITIONAL", ""],
                ["100", "11", "SEA", "DEN", "1", "1", "10", "NA", "76", "Runner rushes right end", "", "", "OUTSIDE_RIGHT"],
                ["100", "12", "SEA", "DEN", "2", "3", "4", "2", "60", "Pass short middle", "C", "TRADITIONAL", ""],
            ],
        )
        self._write(
            root / "players.csv",
            ["nflId", "displayName", "position", "height", "weight", "collegeName"],
            [["44", "Example Runner", "RB", "5-11", "210", "Example State"]],
        )
        self._write(
            root / "tracking_week_1.csv",
            [
                "gameId", "playId", "nflId", "displayName", "frameId", "club",
                "playDirection", "x", "y", "s", "a", "o", "dir", "jerseyNumber", "event",
            ],
            [
                ["100", play, "44", "Example Runner", frame, "SEA", "left", "80", "10", "1", "0", "270", "270", "24", ""]
                for play in ("10", "11", "12")
                for frame in ("1", "2")
            ],
        )


if __name__ == "__main__":
    unittest.main()
