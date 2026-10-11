from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ftbdata.catalog import (
    CatalogValidationError,
    PlayFilters,
    TrackingCatalog,
)
from ftbdata.cli import main


class TrackingCatalogTest(unittest.TestCase):
    def test_ingest_search_health_and_load_play(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            release.mkdir()
            self._write_release(release)
            catalog = TrackingCatalog(root / "football.duckdb")

            report = catalog.ingest_release(release)

            self.assertFalse(report.reused)
            self.assertEqual((report.games, report.plays, report.players, report.tracking_files), (1, 2, 2, 1))
            self.assertTrue(any("player_play.csv" in warning for warning in report.warnings))
            self.assertEqual(len(report.fingerprint), 64)

            repeated = catalog.ingest_release(release)
            self.assertTrue(repeated.reused)
            self.assertEqual(repeated.fingerprint, report.fingerprint)

            page = catalog.find_plays(
                PlayFilters(season=2022, offense="sea", play_type="pass", text="complete"),
                page_size=10,
            )
            self.assertEqual(page.total, 1)
            self.assertEqual(page.items[0].play_id, "10")
            self.assertEqual(page.items[0].play_type, "pass")

            play = catalog.load_play("100", "10")
            self.assertEqual(play["play"]["normalizedDirection"], "right")
            self.assertEqual(play["play"]["absoluteYardline"], 40.0)
            self.assertEqual(play["source"]["releaseFingerprint"], report.fingerprint)
            self.assertEqual(len(play["frames"]), 2)

            health = catalog.data_health()
            self.assertTrue(health.ready)
            self.assertEqual((health.games, health.plays, health.players, health.tracking_files), (1, 2, 2, 1))

            cli_database = root / "cli.duckdb"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main([
                    "ingest", "bdb", "--input", str(release), "--database", str(cli_database),
                ])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["plays"], 2)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main([
                    "plays", "--database", str(cli_database),
                    "--offense", "SEA", "--play-type", "rush",
                ])
            self.assertEqual(exit_code, 0)
            listed_play = json.loads(output.getvalue())["items"][0]
            self.assertEqual(listed_play["play_id"], "11")
            self.assertIsNone(listed_play["yards_gained"])

            export_path = root / "play.json"
            with redirect_stdout(io.StringIO()):
                exit_code = main([
                    "export", "--database", str(cli_database),
                    "--game-id", "100", "--play-id", "10", "--output", str(export_path),
                ])
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(export_path.read_text())["play"]["playId"], "10")

    def test_invalid_release_reports_all_discoverable_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._write(root / "games.csv", ["gameId", "season"], [["1", "2022"]])

            with self.assertRaises(CatalogValidationError) as caught:
                TrackingCatalog(root / "catalog.duckdb").ingest_release(root)

        message = str(caught.exception)
        self.assertIn("games.csv is missing required columns", message)
        self.assertIn("Missing required plays.csv", message)
        self.assertIn("Missing required players.csv", message)
        self.assertIn("No tracking_week_*.csv", message)

    def test_health_is_not_ready_before_ingestion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            health = TrackingCatalog(Path(directory) / "missing.duckdb").data_health()
        self.assertFalse(health.ready)
        self.assertEqual(health.plays, 0)

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
            ],
        )
        self._write(
            root / "players.csv",
            ["nflId", "displayName", "position", "height", "weight", "collegeName"],
            [
                ["44", "Example Runner", "RB", "5-11", "210", "Example State"],
                ["55", "Example Defender", "LB", "6-2", "235", "Example Tech"],
            ],
        )
        self._write(
            root / "tracking_week_1.csv",
            [
                "gameId", "playId", "nflId", "displayName", "frameId", "club",
                "playDirection", "x", "y", "s", "a", "o", "dir", "jerseyNumber", "event",
            ],
            [
                ["100", "10", "44", "Example Runner", "1", "SEA", "left", "80", "10", "1", "0", "270", "270", "24", ""],
                ["100", "10", "55", "Example Defender", "1", "DEN", "left", "77", "11", "1", "0", "90", "90", "55", ""],
                ["100", "10", "", "football", "1", "football", "left", "81", "10.5", "0", "0", "", "", "", ""],
                ["100", "10", "44", "Example Runner", "2", "SEA", "left", "79", "10", "3", "1", "270", "270", "24", "ball_snap"],
                ["100", "10", "55", "Example Defender", "2", "DEN", "left", "76", "11", "2", "1", "90", "90", "55", "ball_snap"],
                ["100", "10", "", "football", "2", "football", "left", "80", "10.5", "0", "0", "", "", "", "ball_snap"],
            ],
        )

    @staticmethod
    def _write(path: Path, headers: list[str], rows: list[list[str]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
