from __future__ import annotations

import copy
import csv
import io
import json
import math
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from fastapi.testclient import TestClient

from ftbdata import quality
from ftbdata.api import create_app
from ftbdata.catalog import PlayFilters, TrackingCatalog
from ftbdata.cli import main
from ftbdata.field import FIELD_LENGTH, FIELD_WIDTH
from ftbdata.tracking import build_play, extract_play, make_demo_play, scan_tracking_file

HEADERS = [
    "gameId", "playId", "nflId", "displayName", "frameId", "time", "club",
    "playDirection", "x", "y", "s", "a", "o", "dir", "jerseyNumber", "event",
]
EVENTS = {5: "ball_snap", 15: "pass_forward", 22: "pass_arrived"}
START = datetime(2022, 9, 8, 20, 24, 5, tzinfo=timezone.utc)

Row = dict[str, str]


def play_rows(
    play_id: str = "10",
    *,
    frames: range = range(1, 31),
    direction: str = "right",
    events: dict[int, str] = EVENTS,
) -> list[Row]:
    """A clean 22-player play in which everyone runs at a constant velocity, as the source reports it.

    Rows are written the way the source would for ``direction``: a leftward play has its x, y, dir
    and o mirrored.
    """

    rows: list[Row] = []
    for frame in frames:
        stamp = (START + timedelta(milliseconds=100 * (frame - 1))).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        entities = []
        for index in range(22):
            heading = 20.0 + index * 12.0  # degrees, 0 toward +y and 90 toward +x
            speed = 3.0 + index % 5
            step = speed / 10.0
            x = 40.0 + index * 1.5 + frame * step * math.sin(math.radians(heading))
            y = 8.0 + index * 1.7 + frame * step * math.cos(math.radians(heading))
            club = "SEA" if index < 11 else "DEN"
            entities.append((str(100 + index), f"Player {index}", club, x, y, speed, heading, 20 + index))
        entities.append(("", "football", "football", 60.0 + frame * 0.2, 26.6, 2.0, None, None))

        for nfl_id, name, club, x, y, speed, heading, jersey in entities:
            orientation = heading
            if direction == "left":
                x, y = FIELD_LENGTH - x, FIELD_WIDTH - y
                heading = None if heading is None else (heading + 180.0) % 360.0
                orientation = heading
            rows.append({
                "gameId": "1", "playId": play_id, "nflId": nfl_id, "displayName": name,
                "frameId": str(frame), "time": stamp, "club": club, "playDirection": direction,
                "x": f"{x:.3f}", "y": f"{y:.3f}", "s": f"{speed:.2f}", "a": "1.0",
                "o": "" if orientation is None else f"{orientation:.1f}",
                "dir": "" if heading is None else f"{heading:.1f}",
                "jerseyNumber": "" if jersey is None else str(jersey),
                "event": events.get(frame, ""),
            })
    return rows


def build(rows: list[Row], *, headers: list[str] | None = None, line: str = "60") -> dict:
    return build_play(
        rows,
        frozenset(headers or HEADERS),
        tracking_file="tracking_week_1.csv",
        game_key="1",
        play_key=rows[0]["playId"],
        play_row={
            "possessionTeam": "SEA", "defensiveTeam": "DEN", "absoluteYardlineNumber": line,
            "playDescription": "Test play",
        },
        game_row={},
        player_lookup={},
    )


def checks(play: dict) -> dict[str, dict]:
    return {item["id"]: item for item in play["provenance"]["validation"]["checks"]}


def status_of(play: dict) -> str:
    return play["provenance"]["validation"]["status"]


class PlayQualityTest(unittest.TestCase):
    def test_clean_play_is_valid_in_both_directions_and_rotates_consistently(self) -> None:
        right = build(play_rows(direction="right"), line="64")
        left = build(play_rows(direction="left"), line=str(FIELD_LENGTH - 64))

        for play in (right, left):
            self.assertEqual(status_of(play), "valid", play["provenance"]["validation"]["checks"])
            self.assertEqual(checks(play)["heading"]["status"], "pass")
            self.assertEqual(checks(play)["yardline"]["status"], "pass")
        self.assertEqual(checks(left)["direction"]["detail"], "Original direction left; rotated 180° (x, y, dir, o, yard line)")
        self.assertTrue(left["provenance"]["direction"]["rotated"])
        self.assertFalse(right["provenance"]["direction"]["rotated"])
        # Normalization makes the two source encodings of the same play identical.
        self.assertEqual(
            [frame["entities"] for frame in right["frames"]][3][:3],
            [frame["entities"] for frame in left["frames"]][3][:3],
        )

    def test_heading_check_catches_direction_that_was_not_transformed_with_position(self) -> None:
        play = build(play_rows())
        tampered = copy.deepcopy(play)
        for frame in tampered["frames"]:
            for entity in frame["entities"]:
                if entity["direction"] is not None:
                    entity["direction"] = (entity["direction"] + 180.0) % 360.0

        result = quality.assess_play(tampered, None)

        self.assertEqual(next(item for item in result["checks"] if item["id"] == "heading")["status"], "warning")
        self.assertEqual(result["status"], "incomplete")

    def test_missing_ball_frames_are_reported_as_intervals(self) -> None:
        rows = [row for row in play_rows() if not (row["displayName"] == "football" and 10 <= int(row["frameId"]) <= 12)]
        play = build(rows)

        self.assertEqual(checks(play)["ball"]["status"], "warning")
        self.assertIn("missing in frames 10–12", checks(play)["ball"]["detail"])
        self.assertEqual(checks(play)["ball"]["count"], 3)
        self.assertEqual(status_of(play), "incomplete")
        self.assertEqual(len(play["frames"]), 30)

    def test_missing_frames_leave_a_visible_gap_in_time(self) -> None:
        rows = [row for row in play_rows() if int(row["frameId"]) not in (12, 13, 14)]
        play = build(rows)

        self.assertEqual(checks(play)["cadence"]["status"], "warning")
        self.assertIn("3 frames missing in 1 gap", checks(play)["cadence"]["detail"])
        after_gap = next(frame for frame in play["frames"] if frame["frameId"] == 15)
        self.assertEqual(after_gap["timeMs"], 1400)  # not 1100: the elapsed time is preserved

    def test_irregular_timestamps_break_the_cadence_check(self) -> None:
        rows = play_rows()
        for row in rows:
            if row["frameId"] == "9":
                row["time"] = (START + timedelta(milliseconds=800 + 70)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

        play = build(rows)

        self.assertEqual(checks(play)["cadence"]["status"], "warning")
        self.assertIn("timestamp steps deviate", checks(play)["cadence"]["detail"])

    def test_entity_major_rows_and_second_precision_timestamps_are_valid(self) -> None:
        rows = play_rows()
        for row in rows:
            row["time"] = row["time"].split(".")[0] + "Z"
        rows.sort(key=lambda row: (row["displayName"], int(row["frameId"])))

        play = build(rows)

        self.assertEqual(checks(play)["frame-order"]["status"], "pass")
        self.assertEqual(checks(play)["cadence"]["status"], "pass")
        self.assertIn("source timestamps have 1 s precision", checks(play)["cadence"]["detail"])

    def test_coordinates_are_graded_by_how_far_they_leave_the_field(self) -> None:
        def with_x(value: str) -> dict:
            rows = play_rows()
            rows[0]["x"] = value
            return build(rows)

        inside_margin = with_x("120.8")
        self.assertEqual(checks(inside_margin)["coordinates"]["status"], "info")
        self.assertEqual(status_of(inside_margin), "valid")

        tracked_off_field = with_x("136.1")
        self.assertEqual(checks(tracked_off_field)["coordinates"]["status"], "info")
        self.assertEqual(status_of(tracked_off_field), "valid")

        well_outside = with_x("145.0")
        self.assertEqual(checks(well_outside)["coordinates"]["status"], "warning")
        self.assertEqual(status_of(well_outside), "incomplete")

        corrupt = with_x("500")
        self.assertEqual(checks(corrupt)["coordinates"]["status"], "error")
        self.assertEqual(status_of(corrupt), "invalid")

    def test_unreadable_and_duplicate_rows_are_counted_not_dropped_silently(self) -> None:
        rows = play_rows()
        rows[0]["x"] = ""
        rows.append(dict(rows[5]))
        play = build(rows)

        self.assertEqual(checks(play)["rows"]["status"], "error")
        self.assertIn("1 duplicate player rows", checks(play)["rows"]["detail"])
        self.assertIn("1 rows with missing or non-numeric values were skipped", checks(play)["rows"]["detail"])
        self.assertEqual(status_of(play), "invalid")

    def test_sparse_unparseable_rows_make_a_play_incomplete(self) -> None:
        rows = play_rows()
        rows[0]["x"] = "NA"

        play = build(rows)

        self.assertEqual(checks(play)["rows"]["status"], "warning")
        self.assertEqual(checks(play)["rows"]["count"], 1)
        self.assertEqual(status_of(play), "incomplete")

    def test_out_of_order_frames_are_sorted_and_reported(self) -> None:
        rows = play_rows()
        frame_3 = [row for row in rows if row["frameId"] == "3"]
        frame_4 = [row for row in rows if row["frameId"] == "4"]
        rest = [row for row in rows if row["frameId"] not in ("3", "4")]
        reordered = [row for row in rest if int(row["frameId"]) < 3] + frame_4 + frame_3 + [
            row for row in rest if int(row["frameId"]) > 4
        ]

        play = build(reordered)

        self.assertEqual(checks(play)["frame-order"]["status"], "warning")
        self.assertEqual([frame["frameId"] for frame in play["frames"]], list(range(1, 31)))

    def test_player_identity_must_be_stable(self) -> None:
        switched = play_rows()
        for row in switched:
            if row["nflId"] == "100" and int(row["frameId"]) > 10:
                row["club"] = "DEN"
        self.assertEqual(checks(build(switched))["identity"]["status"], "error")

        dropped = [row for row in play_rows() if not (row["nflId"] == "105" and int(row["frameId"]) > 20)]
        play = build(dropped)
        self.assertEqual(checks(play)["identity"]["status"], "warning")
        self.assertEqual(checks(play)["entity-count"]["status"], "warning")
        self.assertIn("21 players in 10", checks(play)["entity-count"]["detail"])
        self.assertTrue(any(
            len([e for e in frame["entities"] if e["kind"] == "player"]) == 21 for frame in play["frames"]
        ), "frames with fewer players are kept")

    def test_extra_ball_rows_are_an_entity_anomaly(self) -> None:
        rows = play_rows()
        extra = dict(next(row for row in rows if row["displayName"] == "football" and row["frameId"] == "7"))
        rows.append(extra)

        play = build(sorted(rows, key=lambda row: int(row["frameId"])))

        self.assertIn("more than one football row", checks(play)["entity-count"]["detail"])

    def test_event_order_is_checked(self) -> None:
        backwards = build(play_rows(events={5: "pass_forward", 15: "ball_snap", 22: "pass_arrived"}))
        self.assertEqual(checks(backwards)["events"]["status"], "warning")
        self.assertIn("occur before the snap", checks(backwards)["events"]["detail"])

        reversed_pass = build(play_rows(events={5: "ball_snap", 15: "pass_arrived", 22: "pass_forward"}))
        self.assertIn("pass_arrived precedes the pass release", checks(reversed_pass)["events"]["detail"])

        no_events = build(play_rows(events={}))
        self.assertEqual(checks(no_events)["events"]["status"], "info")
        self.assertEqual(status_of(no_events), "valid")

        legacy_motion = build(play_rows(events={5: "ball_snap", 7: "man_in_motion", 15: "handoff"}))
        self.assertEqual(checks(legacy_motion)["events"]["status"], "pass")

    def test_unknown_direction_is_not_silently_treated_as_normalized(self) -> None:
        headers = [name for name in HEADERS if name != "playDirection"]
        rows = [{k: v for k, v in row.items() if k != "playDirection"} for row in play_rows()]

        play = build(rows, headers=headers, line="")

        self.assertEqual(play["play"]["normalizedDirection"], "unknown")
        self.assertEqual(checks(play)["direction"]["status"], "warning")
        self.assertEqual(status_of(play), "incomplete")

    def test_line_of_scrimmage_must_agree_with_the_ball_at_the_snap(self) -> None:
        play = build(play_rows(), line="90")

        self.assertEqual(checks(play)["yardline"]["status"], "warning")

    def test_absent_and_empty_source_columns_are_listed_without_degrading_the_play(self) -> None:
        headers = [name for name in HEADERS if name not in ("a", "o")]
        rows = [{k: v for k, v in row.items() if k not in ("a", "o")} for row in play_rows()]
        for row in rows:
            row["event"] = ""

        play = build(rows, headers=headers)

        self.assertEqual(play["provenance"]["fields"]["missing"], ["acceleration", "orientation", "event"])
        self.assertIn("speed", play["provenance"]["fields"]["available"])
        self.assertEqual(checks(play)["source-fields"]["status"], "info")
        self.assertEqual(status_of(play), "valid")

    def test_demo_is_generated_and_does_not_claim_measurements(self) -> None:
        demo = make_demo_play(64)

        self.assertEqual(demo["provenance"]["validation"]["status"], "generated")
        self.assertEqual(checks(demo)["heading"]["status"], "unavailable")
        self.assertIsNone(demo["provenance"]["release"])

    def test_scan_matches_single_play_extraction_and_flags_split_plays(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first, second = play_rows("10"), play_rows("11")
            # Play 10 reappears after play 11 started: its rows are not contiguous.
            write(root / "tracking_week_1.csv", HEADERS, first[:200] + second + first[200:])
            write(root / "plays.csv", ["gameId", "playId", "possessionTeam", "defensiveTeam"], [
                ["1", "10", "SEA", "DEN"], ["1", "11", "SEA", "DEN"], ["1", "12", "SEA", "DEN"],
            ])
            results = dict(scan_tracking_file(
                root / "tracking_week_1.csv",
                plays=read_plays(root / "plays.csv"),
                games={}, players={},
            ))
            clean = extract_play(root / "tracking_week_1.csv", 1, 11, plays_path=root / "plays.csv")

        self.assertEqual(set(results), {("1", "10"), ("1", "11")})
        self.assertIn("not contiguous", results[("1", "10")])
        self.assertEqual(results[("1", "11")]["provenance"]["validation"], clean["provenance"]["validation"])


class QualityCatalogTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.release = root / "nfl-big-data-bowl-2025"
        self.release.mkdir()
        self.database = root / "football.duckdb"
        self.write_release(self.release)
        self.catalog = TrackingCatalog(self.database)

    def write_release(self, release: Path) -> None:
        write(release / "games.csv", ["gameId", "season", "week", "gameDate", "homeTeamAbbr", "visitorTeamAbbr"], [
            ["1", "2022", "1", "09/08/2022", "SEA", "DEN"],
        ])
        write(release / "plays.csv", [
            "gameId", "playId", "possessionTeam", "defensiveTeam", "quarter", "down", "yardsToGo",
            "absoluteYardlineNumber", "playDescription",
        ], [
            ["1", "10", "SEA", "DEN", "1", "1", "10", "64", "Clean play"],
            ["1", "11", "SEA", "DEN", "1", "2", "5", "64", "Play missing the ball for a stretch"],
            ["1", "12", "SEA", "DEN", "1", "3", "5", "64", "Play with no tracking rows"],
            ["1", "13", "SEA", "DEN", "1", "4", "5", "64", "Play with a corrupt position"],
        ])
        write(release / "players.csv", ["nflId", "displayName", "position"], [["100", "Player 0", "QB"]])
        short_ball = [
            row for row in play_rows("11")
            if not (row["displayName"] == "football" and int(row["frameId"]) > 25)
        ]
        corrupt = play_rows("13")
        corrupt[3]["y"] = "-80"
        write(release / "tracking_week_1.csv", HEADERS, play_rows("10") + short_ball + corrupt)

    def test_ingest_emits_a_machine_readable_report_and_persists_it(self) -> None:
        report = self.catalog.ingest_release(self.release)

        counts = report.quality.overall
        self.assertEqual((counts.plays, counts.valid, counts.incomplete, counts.invalid), (4, 1, 1, 2))
        self.assertEqual(counts.valid_rate, 0.25)
        by_check = {item.id: item.counts for item in report.quality.checks}
        self.assertEqual(by_check["ball"]["warning"], 1)
        self.assertEqual(by_check["ball"]["pass"], 3)
        self.assertEqual(by_check["coordinates"]["error"], 1)
        self.assertEqual(by_check["rows"]["error"], 1)
        self.assertEqual([(w.season, w.week, w.counts.plays) for w in report.quality.weeks], [(2022, 1, 4)])

        repeated = self.catalog.ingest_release(self.release)
        self.assertTrue(repeated.reused)
        self.assertEqual(repeated.quality, report.quality)
        self.assertEqual(self.catalog.data_health().quality, report.quality)

    def test_search_summaries_and_filters_carry_quality(self) -> None:
        self.catalog.ingest_release(self.release)

        everything = self.catalog.find_plays().items
        self.assertEqual({item.play_id: item.quality_status for item in everything}, {
            "10": "valid", "11": "incomplete", "12": "invalid", "13": "invalid",
        })
        incomplete = self.catalog.find_plays(PlayFilters(quality_status="incomplete"))
        self.assertEqual([item.play_id for item in incomplete.items], ["11"])
        with self.assertRaises(ValueError):
            self.catalog.find_plays(PlayFilters(quality_status="bogus"))

    def test_served_play_carries_compact_provenance(self) -> None:
        report = self.catalog.ingest_release(self.release)

        provenance = self.catalog.load_play("1", "11")["provenance"]

        self.assertEqual(provenance["release"]["name"], "nfl-big-data-bowl-2025")
        self.assertEqual(provenance["release"]["competitionYear"], 2025)
        self.assertEqual(provenance["release"]["season"], 2022)
        self.assertEqual(provenance["release"]["fingerprint"], report.fingerprint)
        self.assertEqual(provenance["files"], ["games.csv", "plays.csv", "players.csv", "tracking_week_1.csv"])
        self.assertEqual(provenance["nflverse"]["status"], "unavailable")
        self.assertEqual(provenance["software"]["name"], "football-analysis")
        self.assertEqual(provenance["validation"]["status"], "incomplete")
        self.assertNotIn(self.directory.name, json.dumps(provenance))
        # The stored assessment and the one served with the play are the same computation.
        stored = {item["play_id"]: item for item in self.catalog.play_quality(("valid", "incomplete", "invalid"))}
        self.assertEqual(stored["11"]["findings"], quality.non_pass_checks(provenance["validation"]))

    def test_cli_quality_report(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["ingest", "bdb", "--input", str(self.release), "--database", str(self.database)]), 0)

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["quality", "--database", str(self.database)]), 0)
        body = json.loads(output.getvalue())

        self.assertEqual(body["report"]["overall"]["invalid"], 2)
        self.assertEqual([item["play_id"] for item in body["plays"]], ["11", "12", "13"])
        self.assertTrue(all(item["findings"] for item in body["plays"]))

        output = io.StringIO()
        with redirect_stdout(output):
            main(["quality", "--database", str(self.database), "--status", "invalid", "--summary-only"])
        self.assertNotIn("plays", json.loads(output.getvalue()))

    def test_api_serves_quality_everywhere_it_is_disclosed(self) -> None:
        self.catalog.ingest_release(self.release)
        client = TestClient(create_app(self.database))

        health = client.get("/data-health").json()["quality"]
        self.assertEqual(health["overall"]["plays"], 4)
        self.assertEqual(health["overall"]["validRate"], 0.25)
        self.assertEqual(health["weeks"], [{"season": 2022, "week": 1, "plays": 4, "valid": 1, "incomplete": 1, "invalid": 2, "validRate": 0.25}])
        self.assertIn({"id": "ball", "pass": 3, "info": 0, "unavailable": 0, "warning": 1, "error": 0}, health["checks"])

        listed = client.get("/plays", params={"quality_status": "valid"}).json()
        self.assertEqual([(item["playId"], item["qualityStatus"]) for item in listed["items"]], [("10", "valid")])
        self.assertEqual(client.get("/plays", params={"quality_status": "nope"}).status_code, 422)

        play = client.get("/plays/1/10").json()
        self.assertEqual(play["provenance"]["validation"]["status"], "valid")
        self.assertEqual(play["provenance"]["fields"]["missing"], [])
        self.assertEqual(play["frames"][1]["timeMs"], 100)


def write(path: Path, headers: list[str], rows: list[list[str]] | list[Row]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([row[header] for header in headers] if isinstance(row, dict) else row)


def read_plays(path: Path) -> dict[tuple[str, ...], dict[str, str]]:
    from ftbdata.tracking import read_lookup

    return read_lookup(path, ("gameId", "playId"))


if __name__ == "__main__":
    unittest.main()
