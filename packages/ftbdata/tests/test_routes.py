from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ftbdata import pass_window, routes
from ftbdata.api import create_app
from ftbdata.catalog import TrackingCatalog
from ftbdata.field import FIELD_LENGTH, FIELD_WIDTH
from test_pass_window import GAME_ID, input_rows, output_rows, supplementary_row, write_release


def sample() -> dict:
    context = supplementary_row("101", description="pass")
    context.update(route_of_targeted_receiver="OUT", team_coverage_man_zone="ZONE")
    return pass_window.build_play(
        input_rows("101", frames=12, direction="left", output_frames=5),
        output_rows("101", frames=5), context,
        input_file="input_2023_w01.csv", output_file="output_2023_w01.csv",
    )


class RouteGeometryTest(unittest.TestCase):
    def test_nonfinite_landing_is_unavailable(self) -> None:
        rows = input_rows("101", frames=2, direction="right", output_frames=0)
        rows[0]["ball_land_x"] = "inf"
        play = pass_window.build_play(rows, [], supplementary_row("101", description="pass"),
                                      input_file="input.csv", output_file=None)
        self.assertIsNone(play["play"]["ballLanding"])
        self.assertIsNotNone(routes.describe(play))

    def test_metadata_roles_and_landing_share_normalization(self) -> None:
        play = sample()
        window = play["play"]["passWindow"]
        self.assertEqual((window["route"], window["coverage"], window["targetReceiverId"]), ("OUT", "ZONE", "2"))
        self.assertEqual((window["releaseFrameId"], window["arrivalFrameId"]), (12, 17))
        receiver = next(entity for entity in play["frames"][-1]["entities"] if entity["id"] == "2")
        self.assertEqual(receiver["role"], "Targeted Receiver")
        self.assertTrue(receiver["playerToPredict"])
        self.assertEqual(play["play"]["ballLanding"], {"x": FIELD_LENGTH - 25, "y": round(FIELD_WIDTH - 8, 3)})
        route = routes.describe(play)
        self.assertEqual(len(route["points"]), 21)
        self.assertEqual(route["points"][0], {"x": -6.6, "y": 0.0})
        self.assertEqual(route["points"][-1], {"x": 0.0, "y": 0.0})
        self.assertEqual(route["observedSeconds"], 1.1)

    def test_translation_and_future_positions_do_not_change_similarity(self) -> None:
        play = sample()
        changed = copy.deepcopy(play)
        for frame in changed["frames"]:
            for entity in frame["entities"]:
                entity["x"] += 3 if frame["frameId"] <= 12 else 30
                entity["y"] += 5
        changed["play"]["ballLanding"] = {"x": 100, "y": 10}
        changed["play"]["passWindow"]["route"] = "GO"
        self.assertEqual(routes.signature(routes.describe(play)), routes.signature(routes.describe(changed)))

    def test_equivalent_left_and_right_plays_match(self) -> None:
        rows = input_rows("101", frames=12, direction="left", output_frames=0)
        for row in rows:
            row.update(play_direction="right", x=str(FIELD_LENGTH - float(row["x"])),
                       y=str(FIELD_WIDTH - float(row["y"])))
        right = pass_window.build_play(rows, [], supplementary_row("101", description="pass"),
                                       input_file="input.csv", output_file=None)
        self.assertEqual(routes.signature(routes.describe(sample())), routes.signature(routes.describe(right)))

    def test_gaps_duplicates_unknown_direction_and_missing_target_are_unavailable(self) -> None:
        for fault in ("gap", "duplicate", "direction", "target", "nonfinite", "short"):
            with self.subTest(fault=fault):
                play = sample()
                if fault == "gap":
                    play["frames"][3]["entities"] = [e for e in play["frames"][3]["entities"] if e["id"] != "2"]
                elif fault == "duplicate":
                    play["frames"][0]["entities"].append(play["frames"][0]["entities"][1])
                elif fault == "direction":
                    play["play"]["normalizedDirection"] = "unknown"
                elif fault == "target":
                    play["play"]["passWindow"]["targetReceiverId"] = None
                elif fault == "short":
                    play["frames"] = play["frames"][:1]
                else:
                    play["frames"][0]["entities"][1]["x"] = float("nan")
                self.assertIsNone(routes.describe(play))


class RouteApiTest(unittest.TestCase):
    def test_browse_similarity_filters_and_reingest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_release(root / "release")
            catalog = TrackingCatalog(root / "catalog.duckdb")
            catalog.ingest_release(root / "release")
            client = TestClient(create_app(catalog.database_path))
            page = client.get("/routes", params={"page_size": 1}).json()
            self.assertEqual((page["indexed"], page["total"], len(page["items"])), (2, 2, 1))
            self.assertIsNone(page["items"][0]["route"])
            self.assertEqual(page["items"][0]["coverageType"], "COVER_2_ZONE")
            self.assertNotIn(str(root), str(page))
            similar = client.get("/routes", params={"game_id": GAME_ID, "play_id": "101"}).json()
            self.assertEqual(similar["reference"]["playId"], "101")
            self.assertEqual([item["playId"] for item in similar["items"]], ["102"])
            # Opposite direction gives opposite release-relative paths: 13.2 * fraction yards apart.
            self.assertAlmostEqual(similar["items"][0]["distanceYards"],
                                   (sum((13.2 * i / 20) ** 2 for i in range(21)) / 21) ** 0.5, places=3)
            self.assertEqual(client.get("/routes?route=GO").json()["total"], 0)
            self.assertEqual(client.get("/routes?coverage=MAN").json()["total"], 0)
            self.assertEqual(client.get("/routes?coverage_type=COVER_2_ZONE").json()["total"], 2)
            self.assertEqual(client.get("/routes?coverage_type=COVER_1_MAN").json()["total"], 0)
            self.assertEqual(page["coverageTypeOptions"], ["COVER_2_ZONE"])
            self.assertEqual(client.get("/routes?game_id=1").status_code, 422)
            self.assertEqual(client.get("/routes?game_id=1&play_id=2").status_code, 422)
            self.assertEqual(client.get("/routes?page_size=51").status_code, 422)
            self.assertTrue(catalog.ingest_release(root / "release").reused)
            self.assertEqual(catalog.find_routes()["indexed"], 2)
            with catalog._connect() as connection:
                connection.execute("UPDATE play_quality SET status = 'invalid' WHERE play_id = '102'")
            self.assertEqual(catalog.find_routes()["indexed"], 1)

    def test_old_index_requests_reingest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_release(root / "release")
            catalog = TrackingCatalog(root / "catalog.duckdb")
            catalog.ingest_release(root / "release")
            with catalog._connect() as connection:
                connection.execute("UPDATE catalog_metadata SET value = '5' WHERE key = 'schema_version'")
            client = TestClient(create_app(catalog.database_path))
            self.assertEqual(client.get("/routes").status_code, 503)
            self.assertIn("Re-run", client.get("/routes").json()["detail"])
            self.assertFalse(catalog.ingest_release(root / "release").reused)
            self.assertEqual(client.get("/routes").json()["indexed"], 2)

    def test_legacy_and_missing_catalog_have_explicit_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = TestClient(create_app(root / "catalog.duckdb"))
            self.assertEqual(client.get("/routes").status_code, 503)
            write_release(root / "release")
            catalog = TrackingCatalog(root / "catalog.duckdb")
            catalog.ingest_release(root / "release")
            with catalog._connect() as connection:
                connection.execute("UPDATE catalog_metadata SET value = 'legacy-game' WHERE key = 'source_format'")
            result = client.get("/routes").json()
            self.assertFalse(result["supported"])
            self.assertEqual(result["items"], [])
