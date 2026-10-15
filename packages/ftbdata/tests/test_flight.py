from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ftbdata import flight, pass_window
from ftbdata.api import create_app
from ftbdata.catalog import CatalogError, TrackingCatalog
from ftbdata.field import FIELD_LENGTH, FIELD_WIDTH
from test_pass_window import (
    GAME_ID, INPUT_HEADERS, OUTPUT_HEADERS, SUPPLEMENTARY_HEADERS,
    input_rows, output_rows, supplementary_row, write_csv,
)
from test_routes import sample


class FlightGeometryTest(unittest.TestCase):
    def test_cardinal_bearings_and_zero_speed(self):
        for direction, expected in ((0, (10, 24)), (90, (14, 20)), (180, (10, 16)), (270, (6, 20))):
            play = sample()
            entity = play["frames"][11]["entities"][1]
            entity.update(x=10, y=20, speed=2, direction=direction, orientation=37)
            state = next(s for s in flight.release_states(play)["states"] if s["id"] == entity["id"])
            x, y = flight.project(state, 2)
            self.assertAlmostEqual(x, expected[0])
            self.assertAlmostEqual(y, expected[1])
        entity.update(speed=0)
        state = next(s for s in flight.release_states(play)["states"] if s["id"] == entity["id"])
        self.assertEqual(flight.project(state, 100), (10, 20))

    def test_future_and_outcome_changes_cannot_change_release_state(self):
        play = sample()
        expected = flight.release_states(play)
        for frame in play["frames"][12:]:
            for entity in frame["entities"]:
                entity.update(x=999, y=-100, speed=999, direction=47, playerToPredict=False)
        play["play"]["ballLanding"] = {"x": 999, "y": 999}
        play["play"]["passWindow"].update(route="GO", arrivalFrameId=999)
        self.assertEqual(flight.release_states(play), expected)
        play["frames"] = play["frames"][:12]
        self.assertEqual(flight.release_states(play), expected)

    def test_left_right_rotation_preserves_forecast(self):
        rows = input_rows("101", frames=12, direction="left", output_frames=0)
        for row in rows:
            row.update(play_direction="right", x=str(FIELD_LENGTH - float(row["x"])),
                       y=str(FIELD_WIDTH - float(row["y"])), dir=str((float(row["dir"]) + 180) % 360))
        right = pass_window.build_play(rows, [], supplementary_row("101", description="pass"),
                                       input_file="input.csv", output_file=None)
        self.assertEqual(flight.release_states(sample()), flight.release_states(right))

    def test_missing_speed_direction_duplicate_or_missing_release_is_unavailable(self):
        for fault in ("speed", "direction", "duplicate", "missing"):
            play = sample()
            release = play["frames"][11]
            entity = next(e for e in release["entities"] if e["id"] == "2")
            if fault in ("speed", "direction"):
                entity[fault] = None
            elif fault == "duplicate":
                release["entities"].append(copy.deepcopy(entity))
            else:
                release["entities"].remove(entity)
            forecast = flight.release_states(play)
            self.assertNotIn("2", [s["id"] for s in forecast["states"]])
            self.assertEqual(forecast["unavailable"][0]["id"], "2")
        del play["play"]["passWindow"]
        self.assertIsNotNone(flight.release_states(play)["reason"])

    def test_known_errors_missing_frames_and_final_window(self):
        play = sample()
        forecast = flight.release_states(play)
        for frame in play["frames"][12:]:
            for entity in frame["entities"]:
                state = next(s for s in forecast["states"] if s["id"] == entity["id"])
                x, y = flight.project(state, (frame["frameId"] - 12) / 10)
                entity.update(x=x + 3, y=y + 4)
        # A missing full frame and one missing arrival player stay missing, never bridged.
        play["frames"] = [f for f in play["frames"] if f["frameId"] != 14]
        play["frames"][-1]["entities"].pop()
        score = flight.Scores()
        for _, _, error, final in flight.measurements(play, forecast):
            score.add(error, final)
        report = score.report()
        self.assertEqual((report["samples"], report["missingSamples"], report["endpoints"]), (7, 3, 1))
        self.assertAlmostEqual(report["coordinateRmse"], math.sqrt(12.5))
        self.assertAlmostEqual(report["meanDistance"], 5)
        self.assertAlmostEqual(report["finalDistance"], 5)
        play["play"]["passWindow"]["arrivalFrameId"] = None
        self.assertEqual(list(flight.measurements(play, forecast)), [])


class FlightEvaluationTest(unittest.TestCase):
    def test_game_split_report_source_guard_and_api(self):
        heldout_id = "2023090702"
        self.assertTrue(flight.held_out(heldout_id))
        self.assertFalse(flight.held_out(GAME_ID))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs, outputs, contexts = [], [], []
            for game_id in (GAME_ID, heldout_id):
                for play_id in ("101", "102"):
                    ins = input_rows(play_id, frames=12, direction="left", output_frames=5)
                    outs = output_rows(play_id, frames=5)
                    context = supplementary_row(play_id, description="pass")
                    for row in [*ins, *outs, context]:
                        row["game_id"] = game_id
                    inputs.extend(ins)
                    outputs.extend(outs)
                    contexts.append(context)
            source = root / "release"
            write_csv(source / "supplementary_data.csv", SUPPLEMENTARY_HEADERS, contexts)
            write_csv(source / "train/input_2023_w01.csv", INPUT_HEADERS, inputs)
            write_csv(source / "train/output_2023_w01.csv", OUTPUT_HEADERS, outputs)
            catalog = TrackingCatalog(root / "catalog.duckdb")
            catalog.ingest_release(source)
            report = flight.evaluate(catalog)
            self.assertEqual(report["heldOutGames"], [heldout_id])
            self.assertEqual(report["developmentGames"], [GAME_ID])
            self.assertEqual(report["counts"]["scoredPlays"], 2)
            self.assertEqual(report["overall"]["samples"], 20)
            self.assertEqual([row["gameId"] for row in report["byGame"]], [heldout_id])
            self.assertEqual(report["fittedParameters"], 0)
            # Report matches the same per-play scorer used by the visual forecast.
            play = catalog.load_play(heldout_id, "101")
            score = flight.Scores()
            for _, _, error, final in flight.measurements(play, play["flightForecast"]):
                score.add(error, final)
            self.assertAlmostEqual(report["overall"]["coordinateRmse"], score.report()["coordinateRmse"])
            path = root / "report.json"
            path.write_text(json.dumps(report))
            client = TestClient(create_app(catalog.database_path, flight_report=path))
            self.assertEqual(client.get("/flight-report").status_code, 200)
            self.assertEqual(TestClient(create_app(catalog.database_path)).get("/flight-report").status_code, 503)
            report["fingerprint"] = "wrong-source"
            path.write_text(json.dumps(report))
            self.assertEqual(client.get("/flight-report").status_code, 409)
            # A source mutation must not inherit the previous catalog's provenance.
            inputs[0]["x"] = "42"
            write_csv(source / "train/input_2023_w01.csv", INPUT_HEADERS, inputs)
            with self.assertRaisesRegex(CatalogError, "Source files changed"):
                flight.evaluate(catalog)


if __name__ == "__main__":
    unittest.main()
