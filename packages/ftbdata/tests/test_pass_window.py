from __future__ import annotations

import csv
import math
import tempfile
import unittest
from pathlib import Path

from ftbdata import pass_window, quality
from ftbdata.catalog import CatalogValidationError, PlayFilters, TrackingCatalog
from ftbdata.field import FIELD_LENGTH, FIELD_WIDTH

INPUT_HEADERS = [
    "game_id", "play_id", "player_to_predict", "nfl_id", "frame_id", "play_direction",
    "absolute_yardline_number", "player_name", "player_height", "player_weight", "player_birth_date",
    "player_position", "player_side", "player_role", "x", "y", "s", "a", "dir", "o",
    "num_frames_output", "ball_land_x", "ball_land_y",
]
OUTPUT_HEADERS = ["game_id", "play_id", "nfl_id", "frame_id", "x", "y"]
SUPPLEMENTARY_HEADERS = [
    "game_id", "season", "week", "game_date", "game_time_eastern", "home_team_abbr", "visitor_team_abbr",
    "play_id", "play_description", "quarter", "game_clock", "down", "yards_to_go", "possession_team",
    "defensive_team", "yardline_side", "yardline_number", "pre_snap_home_score", "pre_snap_visitor_score",
    "play_nullified_by_penalty", "pass_result", "pass_length", "offense_formation", "receiver_alignment",
    "route_of_targeted_receiver", "play_action", "dropback_type", "dropback_distance", "pass_location_type",
    "defenders_in_the_box", "team_coverage_man_zone", "team_coverage_type", "penalty_yards",
    "pre_penalty_yards_gained", "yards_gained", "expected_points", "expected_points_added",
    "pre_snap_home_team_win_probability", "pre_snap_visitor_team_win_probability",
    "home_team_win_probability_added", "visitor_team_win_probility_added",
]
GAME_ID = "2023090700"

# (nfl_id, name, position, side, role, predicted, start x, start y, heading, speed)
PLAYERS = [
    ("1", "Jared Passer", "QB", "Offense", "Passer", False, 50.0, 26.0, 90.0, 2.0),
    ("2", "Amon Receiver", "WR", "Offense", "Targeted Receiver", True, 40.0, 10.0, 270.0, 6.0),
    ("3", "Trent Corner", "CB", "Defense", "Defensive Coverage", True, 38.0, 11.0, 270.0, 5.0),
    ("4", "Kenneth Murray, Jr.", "MLB", "Defense", "Defensive Coverage", False, 37.0, 30.0, 200.0, 3.0),
]
BALL_LAND = (25.0, 8.0)


def input_rows(
    play_id: str,
    *,
    frames: int,
    direction: str,
    output_frames: int,
    yardline: str = "42",
) -> list[dict[str, str]]:
    """Pre-throw rows for four players moving at constant velocity with a consistent ``dir``."""
    rows = []
    for nfl_id, name, position, side, role, predicted, x0, y0, heading, speed in PLAYERS:
        for frame in range(1, frames + 1):
            step = speed / 10.0 * (frame - 1)
            rows.append({
                "game_id": GAME_ID, "play_id": play_id, "player_to_predict": str(predicted),
                "nfl_id": nfl_id, "frame_id": str(frame), "play_direction": direction,
                "absolute_yardline_number": yardline, "player_name": name, "player_height": "6-1",
                "player_weight": "210", "player_birth_date": "1999-09-07", "player_position": position,
                "player_side": side, "player_role": role,
                "x": f"{x0 + step * math.sin(math.radians(heading)):.2f}",
                "y": f"{y0 + step * math.cos(math.radians(heading)):.2f}",
                "s": f"{speed:.2f}", "a": "0.50", "dir": f"{heading:.2f}", "o": f"{heading:.2f}",
                "num_frames_output": str(output_frames),
                "ball_land_x": str(BALL_LAND[0]), "ball_land_y": str(BALL_LAND[1]),
            })
    return rows


def output_rows(play_id: str, *, frames: int) -> list[dict[str, str]]:
    """Post-throw positions for the predicted players only."""
    rows = []
    for nfl_id, *_rest, x0, y0, _heading, _speed in PLAYERS:
        if nfl_id not in {"2", "3"}:
            continue
        for frame in range(1, frames + 1):
            rows.append({
                "game_id": GAME_ID, "play_id": play_id, "nfl_id": nfl_id, "frame_id": str(frame),
                "x": f"{x0 - 6.0 - frame * 0.5:.2f}", "y": f"{y0:.2f}",
            })
    return rows


def supplementary_row(play_id: str, *, description: str, yards_gained: str = "18") -> dict[str, str]:
    row = {name: "NA" for name in SUPPLEMENTARY_HEADERS}
    row.update({
        "game_id": GAME_ID, "season": "2023", "week": "1", "game_date": "09/07/2023",
        "game_time_eastern": "20:20:00", "home_team_abbr": "KC", "visitor_team_abbr": "DET",
        "play_id": play_id, "play_description": description, "quarter": "1", "game_clock": "07:30",
        "down": "3", "yards_to_go": "12", "possession_team": "DET", "defensive_team": "KC",
        "yardline_side": "DET", "yardline_number": "32", "pass_result": "C", "dropback_type": "TRADITIONAL",
        "offense_formation": "SHOTGUN", "team_coverage_type": "COVER_2_ZONE", "yards_gained": yards_gained,
        "expected_points_added": "2.94",
    })
    return row


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]], *, quote_all: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=headers, quoting=csv.QUOTE_ALL if quote_all else csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        writer.writerows(rows)


def write_release(root: Path, *, week_two_output: bool = True) -> None:
    """Week 1: a leftward play with post-throw frames, a rightward play without them, and a
    supplementary-only play that has no tracking."""
    write_csv(
        root / "supplementary_data.csv",
        SUPPLEMENTARY_HEADERS,
        [
            supplementary_row("101", description="(7:30) J.Passer pass deep left to A.Receiver for 18 yards"),
            supplementary_row("102", description="(7:00) J.Passer pass short right incomplete", yards_gained="0"),
            supplementary_row("999", description="(6:00) Untracked pass play"),
        ],
        quote_all=True,
    )
    write_csv(
        root / "train" / "input_2023_w01.csv",
        INPUT_HEADERS,
        input_rows("101", frames=12, direction="left", output_frames=5)
        + input_rows("102", frames=12, direction="right", output_frames=4),
    )
    write_csv(root / "train" / "output_2023_w01.csv", OUTPUT_HEADERS, output_rows("101", frames=5))


class PassWindowCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.release = self.root / "nfl-big-data-bowl-2026-analytics"
        write_release(self.release)
        self.catalog = TrackingCatalog(self.root / "football.duckdb")

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_ingest_catalogs_only_tracked_plays_and_discloses_coverage(self) -> None:
        report = self.catalog.ingest_release(self.release)

        self.assertEqual((report.games, report.plays, report.players, report.tracking_files), (1, 2, 4, 1))
        warnings = " ".join(report.warnings)
        self.assertIn("1 supplementary plays have no tracking", warnings)
        self.assertIn("passer, route runners, and coverage defenders", warnings)
        self.assertIn("1 plays have no post-throw output rows", warnings)
        self.assertEqual(report.quality.overall.plays, 2)
        self.assertEqual(report.quality.overall.valid, 2)

        self.assertTrue(self.catalog.ingest_release(self.release).reused)

    def test_search_uses_supplementary_context(self) -> None:
        self.catalog.ingest_release(self.release)

        page = self.catalog.find_plays(PlayFilters(season=2023, week=1, offense="det", play_type="pass"))
        self.assertEqual([item.play_id for item in page.items], ["101", "102"])
        first = page.items[0]
        self.assertEqual((first.defense, first.quarter, first.down, first.yards_to_go), ("KC", 1, 3, 12.0))
        self.assertEqual(first.yards_gained, 18.0)
        self.assertEqual(first.game_date, "09/07/2023")
        self.assertEqual(self.catalog.find_plays(PlayFilters(text="untracked")).total, 0)

    def test_load_play_joins_pre_throw_and_in_flight_frames(self) -> None:
        self.catalog.ingest_release(self.release)

        play = self.catalog.load_play(GAME_ID, "101")

        self.assertEqual(play["source"]["trackingFormat"], "pass-window")
        self.assertEqual(play["source"]["directionMethod"], "source")
        self.assertEqual(play["play"]["originalDirection"], "left")
        self.assertEqual(play["play"]["absoluteYardline"], FIELD_LENGTH - 42.0)
        self.assertEqual((play["play"]["offense"], play["play"]["defense"]), ("DET", "KC"))
        self.assertEqual(play["play"]["ballLanding"], {"x": FIELD_LENGTH - 25.0, "y": round(FIELD_WIDTH - 8.0, 3)})

        frames = play["frames"]
        self.assertEqual([frame["frameId"] for frame in frames], list(range(1, 18)))
        self.assertEqual([frame["timeMs"] for frame in frames][-1], 1600)
        self.assertEqual(frames[11]["event"], "pass_forward")
        self.assertEqual(frames[16]["event"], "pass_arrived")
        self.assertEqual(len(frames[0]["entities"]), 4)
        self.assertEqual({entity["id"] for entity in frames[12]["entities"]}, {"2", "3"})

        before = next(entity for entity in frames[0]["entities"] if entity["id"] == "4")
        self.assertEqual(
            (before["name"], before["club"], before["position"], before["jersey"]),
            ("Kenneth Murray, Jr.", "KC", "MLB", None),
        )
        self.assertEqual(before["x"], round(FIELD_LENGTH - 37.0, 3))
        self.assertEqual(before["direction"], 20.0)
        self.assertEqual(before["acceleration"], 0.5)

        after = next(entity for entity in frames[12]["entities"] if entity["id"] == "2")
        self.assertEqual(after["x"], round(FIELD_LENGTH - 33.5, 3))
        self.assertEqual((after["club"], after["position"]), ("DET", "WR"))
        self.assertIsNone(after["speed"])
        self.assertIsNone(after["acceleration"])
        self.assertIsNone(after["direction"])
        self.assertIsNone(after["orientation"])

        provenance = play["provenance"]
        self.assertEqual(provenance["release"]["competitionYear"], 2026)
        self.assertEqual(
            provenance["files"], ["supplementary_data.csv", "input_2023_w01.csv", "output_2023_w01.csv"]
        )
        self.assertEqual(provenance["fields"]["missing"], ["event", "time"])

        checks = {check["id"]: check for check in provenance["validation"]["checks"]}
        self.assertEqual(provenance["validation"]["status"], "valid")
        self.assertEqual(checks["ball"]["status"], quality.UNAVAILABLE)
        self.assertEqual(checks["entity-count"]["status"], quality.INFO)
        self.assertIn("4 players before the throw and 2 after", checks["entity-count"]["detail"])
        self.assertEqual(checks["identity"]["status"], quality.PASS)
        self.assertEqual(checks["events"]["status"], quality.INFO)
        self.assertIn("derived", checks["events"]["detail"])
        self.assertEqual(checks["heading"]["status"], quality.PASS)
        self.assertEqual(checks["cadence"]["status"], quality.PASS)

    def test_play_without_output_rows_ends_at_the_throw(self) -> None:
        self.catalog.ingest_release(self.release)

        play = self.catalog.load_play(GAME_ID, "102")

        self.assertEqual(play["play"]["originalDirection"], "right")
        self.assertEqual(play["play"]["absoluteYardline"], 42.0)
        self.assertEqual(len(play["frames"]), 12)
        self.assertEqual(play["frames"][-1]["event"], "pass_forward")
        self.assertNotIn("pass_arrived", [frame["event"] for frame in play["frames"]])
        self.assertEqual(play["provenance"]["files"], ["supplementary_data.csv", "input_2023_w01.csv"])

    def test_missing_columns_fail_with_actionable_errors(self) -> None:
        write_csv(self.release / "train" / "output_2023_w01.csv", ["game_id", "play_id"], [])

        with self.assertRaises(CatalogValidationError) as caught:
            self.catalog.ingest_release(self.release)

        self.assertIn("output_2023_w01.csv is missing required columns: frame_id, nfl_id, x, y", str(caught.exception))


class PassWindowQualityTest(unittest.TestCase):
    def build(self, rows: list[dict[str, str]], output: list[dict[str, str]]) -> dict:
        supplementary = supplementary_row("101", description="pass")
        return pass_window.build_play(
            rows, output, supplementary, input_file="input_2023_w01.csv", output_file="output_2023_w01.csv"
        )

    def test_pre_throw_dropout_still_warns(self) -> None:
        rows = [
            row for row in input_rows("101", frames=12, direction="right", output_frames=5)
            if not (row["nfl_id"] == "4" and row["frame_id"] == "6")
        ]

        play = self.build(rows, output_rows("101", frames=5))

        checks = {check["id"]: check for check in play["provenance"]["validation"]["checks"]}
        self.assertEqual(checks["identity"]["status"], quality.WARNING)
        self.assertIn("missing from some pre-throw frames", checks["identity"]["detail"])
        self.assertEqual(play["provenance"]["validation"]["status"], "incomplete")

    def test_too_many_players_still_warns(self) -> None:
        rows = input_rows("101", frames=3, direction="right", output_frames=0)
        extra = [
            {**row, "nfl_id": str(1000 + index), "player_name": f"Extra {index}"}
            for index in range(20)
            for row in rows
            if row["nfl_id"] == "4" and row["frame_id"] == "1"
        ]

        play = self.build(rows + extra, [])

        checks = {check["id"]: check for check in play["provenance"]["validation"]["checks"]}
        self.assertEqual(checks["entity-count"]["status"], quality.WARNING)
        self.assertIn("more than 22 players", checks["entity-count"]["detail"])


if __name__ == "__main__":
    unittest.main()
