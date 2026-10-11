from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from ftbdata.tracking import extract_play, make_demo_play


class TrackingTest(unittest.TestCase):
    def test_demo_has_ball_and_22_players_per_frame(self) -> None:
        play = make_demo_play(12)
        self.assertEqual(len(play["frames"]), 12)
        self.assertTrue(all(len(frame["entities"]) == 23 for frame in play["frames"]))
        self.assertEqual(play["frames"][10]["event"], "ball_snap")

    def test_extract_rotates_leftward_play_and_keeps_ball(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tracking = root / "tracking.csv"
            plays = root / "plays.csv"
            players = root / "players.csv"
            self._write(
                tracking,
                [
                    "gameId", "playId", "nflId", "displayName", "frameId", "club",
                    "playDirection", "x", "y", "s", "a", "o", "dir", "jerseyNumber", "event",
                ],
                [
                    ["1", "9", "44", "Runner", "2", "SEA", "left", "80", "10", "4", "1", "270", "270", "24", "ball_snap"],
                    ["1", "9", "", "football", "2", "football", "left", "81", "11", "0", "0", "", "", "", "ball_snap"],
                    ["1", "9", "44", "Runner", "1", "SEA", "left", "79", "9", "3", "1", "260", "260", "24", ""],
                ],
            )
            self._write(
                plays,
                ["gameId", "playId", "possessionTeam", "defensiveTeam", "down", "yardsToGo", "absoluteYardlineNumber", "playDescription"],
                [["1", "9", "SEA", "DEN", "2", "8", "80", "Test play"]],
            )
            self._write(players, ["nflId", "displayName", "position"], [["44", "Runner", "RB"]])

            play = extract_play(tracking, 1, 9, plays_path=plays, players_path=players)

        self.assertEqual([frame["frameId"] for frame in play["frames"]], [1, 2])
        runner = next(entity for entity in play["frames"][1]["entities"] if entity["id"] == "44")
        ball = next(entity for entity in play["frames"][1]["entities"] if entity["id"] == "ball")
        self.assertEqual((runner["x"], runner["y"]), (40.0, 43.3))
        self.assertEqual(runner["direction"], 90.0)
        self.assertEqual(runner["position"], "RB")
        self.assertEqual((ball["x"], ball["y"]), (39.0, 42.3))
        self.assertEqual(play["play"]["originalDirection"], "left")
        self.assertEqual(play["play"]["normalizedDirection"], "right")
        self.assertEqual(play["play"]["absoluteYardline"], 40.0)

    @staticmethod
    def _write(path: Path, headers: list[str], rows: list[list[str]]) -> None:
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(headers)
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
