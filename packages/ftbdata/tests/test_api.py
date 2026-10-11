from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ftbdata.api import create_app
from ftbdata.catalog import TrackingCatalog


class TrackingApiTest(unittest.TestCase):
    def test_health_search_and_play_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            release.mkdir()
            self._write_release(release)
            database = root / "football.duckdb"
            TrackingCatalog(database).ingest_release(release)
            client = TestClient(create_app(database))

            process_health = client.get("/health")
            self.assertEqual(process_health.status_code, 200)
            self.assertEqual(process_health.json(), {"status": "ok", "catalogReady": True})

            data_health = client.get("/data-health")
            self.assertEqual(data_health.status_code, 200)
            health_body = data_health.json()
            self.assertEqual(health_body["sourceName"], "release")
            self.assertEqual(health_body["counts"]["plays"], 2)
            self.assertNotIn(str(root), data_health.text)
            self.assertNotIn("sourceRoot", health_body)

            search = client.get(
                "/plays",
                params={"offense": "sea", "play_type": "pass", "text": "complete"},
            )
            self.assertEqual(search.status_code, 200)
            search_body = search.json()
            self.assertEqual(search_body["total"], 1)
            self.assertEqual(search_body["pageSize"], 50)
            self.assertEqual(search_body["items"][0]["playId"], "10")
            self.assertEqual(search_body["items"][0]["yardsGained"], 14.0)

            play = client.get("/plays/100/10")
            self.assertEqual(play.status_code, 200)
            self.assertEqual(play.json()["play"]["title"], "SEA vs DEN")
            self.assertEqual(len(play.json()["frames"]), 2)

            missing = client.get("/plays/100/999")
            self.assertEqual(missing.status_code, 404)
            self.assertIn("not cataloged", missing.json()["detail"])

            invalid = client.get("/plays", params={"page_size": 201})
            self.assertEqual(invalid.status_code, 422)

    def test_missing_catalog_is_reported_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(create_app(Path(directory) / "missing.duckdb"))

            self.assertEqual(
                client.get("/health").json(),
                {"status": "ok", "catalogReady": False},
            )
            self.assertFalse(client.get("/data-health").json()["ready"])
            unavailable = client.get("/plays")
            self.assertEqual(unavailable.status_code, 503)
            self.assertIn("does not exist", unavailable.json()["detail"])

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
                "playDescription", "passResult", "rushLocationType",
            ],
            [
                ["100", "10", "SEA", "DEN", "1", "2", "8", "14", "80", "Pass complete left", "C", ""],
                ["100", "11", "SEA", "DEN", "1", "1", "10", "4", "76", "Runner rushes right end", "", "OUTSIDE_RIGHT"],
            ],
        )
        self._write(
            root / "players.csv",
            ["nflId", "displayName", "position"],
            [["44", "Example Runner", "RB"]],
        )
        self._write(
            root / "tracking_week_1.csv",
            [
                "gameId", "playId", "nflId", "displayName", "frameId", "club",
                "playDirection", "x", "y", "s", "a", "o", "dir", "jerseyNumber", "event",
            ],
            [
                ["100", "10", "44", "Example Runner", "1", "SEA", "right", "40", "20", "1", "0", "90", "90", "24", ""],
                ["100", "10", "", "football", "1", "football", "right", "41", "20", "0", "0", "", "", "", ""],
                ["100", "10", "44", "Example Runner", "2", "SEA", "right", "41", "20", "3", "1", "90", "90", "24", "ball_snap"],
                ["100", "10", "", "football", "2", "football", "right", "42", "20", "0", "0", "", "", "", "ball_snap"],
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
