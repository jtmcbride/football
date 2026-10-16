from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
        expected = {baseline: flight.release_states(play, baseline, damping_rate=2) for baseline in flight.BASELINE_VERSIONS}
        for frame in play["frames"][12:]:
            for entity in frame["entities"]:
                entity.update(x=999, y=-100, speed=999, direction=47, playerToPredict=False)
        play["play"]["ballLanding"] = {"x": 999, "y": 999}
        play["play"]["passWindow"].update(route="GO", arrivalFrameId=999)
        for baseline in flight.BASELINE_VERSIONS:
            self.assertEqual(flight.release_states(play, baseline, damping_rate=2), expected[baseline])
        play["frames"] = play["frames"][:12]
        for baseline in flight.BASELINE_VERSIONS:
            self.assertEqual(flight.release_states(play, baseline, damping_rate=2), expected[baseline])

    def test_left_right_rotation_preserves_forecast(self):
        rows = input_rows("101", frames=12, direction="left", output_frames=0)
        for row in rows:
            row.update(play_direction="right", x=str(FIELD_LENGTH - float(row["x"])),
                       y=str(FIELD_WIDTH - float(row["y"])), dir=str((float(row["dir"]) + 180) % 360))
        right = pass_window.build_play(rows, [], supplementary_row("101", description="pass"),
                                       input_file="input.csv", output_file=None)
        for baseline in flight.BASELINE_VERSIONS:
            self.assertEqual(flight.release_states(sample(), baseline, damping_rate=2), flight.release_states(right, baseline, damping_rate=2))

    def test_damped_integral_limits_and_known_geometry(self):
        # a(t)=2*exp(-t) integrates to 2*(t - 1 + exp(-t)) displacement.
        state = {"x": 10, "y": 20, "vx": 3, "vy": -2, "ax": 2, "ay": -4}
        x, y = flight.project(state, 2, 1)
        self.assertAlmostEqual(x, 16 + 2 * (1 + math.exp(-2)))
        self.assertAlmostEqual(y, 16 - 4 * (1 + math.exp(-2)))
        self.assertEqual(flight.project(state, 0, 1), (10, 20))
        self.assertEqual(flight.project(state, 2, 0), flight.project(state, 2))
        for seconds in (0.1, 1, 10):
            self.assertAlmostEqual(flight.acceleration_weight(seconds, 1e-12), 0.5 * seconds ** 2, places=8)
        self.assertAlmostEqual(flight.acceleration_weight(1, 1e8), 1e-8, places=14)
        for rate in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                flight.project(state, 1, rate)
        self.assertIsNotNone(flight.release_states(sample(), flight.DAMPED)["reason"])
        damped = flight.release_states(sample(), flight.DAMPED, damping_rate=2)
        self.assertEqual(damped["dampingRate"], 2)
        self.assertTrue(damped["states"])

    def test_acceleration_vector_and_known_position_ignore_scalar_acceleration(self):
        play = sample()
        release = next(e for e in play["frames"][11]["entities"] if e["id"] == "2")
        prior = next(e for e in play["frames"][10]["entities"] if e["id"] == "2")
        release.update(x=10, y=20, speed=5, direction=math.degrees(math.atan2(3, 4)))
        prior.update(speed=math.hypot(2.8, 4.1), direction=math.degrees(math.atan2(2.8, 4.1)))
        forecast = flight.release_states(play, flight.ACCELERATION)
        state = next(s for s in forecast["states"] if s["id"] == "2")
        self.assertAlmostEqual(state["ax"], 2)
        self.assertAlmostEqual(state["ay"], -1)
        x, y = flight.project(state, 2)
        self.assertAlmostEqual(x, 20)
        self.assertAlmostEqual(y, 26)
        for frame in play["frames"][12:]:
            for entity in frame["entities"]:
                prediction = next(s for s in forecast["states"] if s["id"] == entity["id"])
                entity["x"], entity["y"] = flight.project(prediction, (frame["frameId"] - 12) / 10)
        self.assertTrue(all(error == 0 for _, _, error, _ in flight.measurements(play, forecast)))
        self.assertTrue(any(error > 0 for _, _, error, _ in flight.measurements(play, flight.release_states(play))))
        for frame in play["frames"]:
            for entity in frame["entities"]:
                entity.update(acceleration=999, orientation=37)
        self.assertEqual(flight.release_states(play, flight.ACCELERATION), forecast)

    def test_acceleration_handles_braking_turning_and_heading_wrap(self):
        for current, previous, expected in (
            ((2, 90), (3, 90), (-10, 0)),
            ((2, 0), (2, 90), (-20, 20)),
            ((2, 1), (2, 359), (40 * math.sin(math.radians(1)), 0)),
        ):
            play = sample()
            release = next(e for e in play["frames"][11]["entities"] if e["id"] == "2")
            prior = next(e for e in play["frames"][10]["entities"] if e["id"] == "2")
            release.update(speed=current[0], direction=current[1])
            prior.update(speed=previous[0], direction=previous[1])
            state = next(s for s in flight.release_states(play, flight.ACCELERATION)["states"] if s["id"] == "2")
            self.assertAlmostEqual(state["ax"], expected[0])
            self.assertAlmostEqual(state["ay"], expected[1])

    def test_acceleration_needs_unique_adjacent_velocity_and_never_falls_back(self):
        for fault in ("frame-gap", "missing-player", "duplicate", "speed", "direction", "cadence"):
            with self.subTest(fault=fault):
                play = sample()
                prior = play["frames"][10]
                entity = next(e for e in prior["entities"] if e["id"] == "2")
                if fault == "frame-gap":
                    play["frames"].remove(prior)
                elif fault == "missing-player":
                    prior["entities"].remove(entity)
                elif fault == "duplicate":
                    prior["entities"].append(copy.deepcopy(entity))
                elif fault == "cadence":
                    prior["timeMs"] -= 100
                else:
                    entity[fault] = None
                cv = flight.release_states(play)
                ca = flight.release_states(play, flight.ACCELERATION)
                self.assertIn("2", [s["id"] for s in cv["states"]])
                self.assertNotIn("2", [s["id"] for s in ca["states"]])
                self.assertEqual(ca["unavailable"][0]["id"], "2")

    def test_zero_acceleration_reduces_to_velocity(self):
        play = sample()
        cv = flight.release_states(play)
        ca = flight.release_states(play, flight.ACCELERATION)
        for velocity, acceleration in zip(cv["states"], ca["states"], strict=True):
            self.assertEqual((acceleration["ax"], acceleration["ay"]), (0, 0))
            for seconds in (0, 0.1, 1, 10):
                self.assertEqual(flight.project(velocity, seconds), flight.project(acceleration, seconds))

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
    def test_damping_selection_cannot_see_held_out_outcomes(self):
        def truth(game_id, rate):
            play = sample()
            play["play"]["gameId"] = game_id
            release = next(e for e in play["frames"][11]["entities"] if e["id"] == "2")
            prior = next(e for e in play["frames"][10]["entities"] if e["id"] == "2")
            release.update(speed=5, direction=90)
            prior.update(speed=4.8, direction=90)
            forecast = flight.release_states(play, flight.DAMPED, damping_rate=rate)
            for frame in play["frames"][12:]:
                for entity in frame["entities"]:
                    state = next(s for s in forecast["states"] if s["id"] == entity["id"])
                    entity["x"], entity["y"] = flight.project(state, (frame["frameId"] - 12) / 10, rate)
            return play

        development, holdout = truth(GAME_ID, 2), truth("2023090702", 8)
        catalog = SimpleNamespace(pass_flight_source=lambda: (None, "fixture", [GAME_ID, "2023090702"]))
        calls = []

        def stream(release, games):
            calls.append(set(games))
            return iter(play for play in (development, holdout) if play["play"]["gameId"] in games)

        with patch("ftbdata.pass_window.iter_plays", side_effect=stream):
            before = flight.evaluate(catalog)
            holdout = truth("2023090702", 0)
            after = flight.evaluate(catalog)
        self.assertEqual(calls, [{GAME_ID}, {"2023090702"}, {GAME_ID}, {"2023090702"}])
        self.assertEqual(before["tuning"], after["tuning"])
        self.assertEqual(before["tuning"]["selectedRate"], 2)
        self.assertEqual(min(before["tuning"]["candidates"], key=lambda c: c["coordinateRmse"])["rate"], 2)
        self.assertNotEqual(before["comparison"]["baselines"][flight.DAMPED]["overall"], after["comparison"]["baselines"][flight.DAMPED]["overall"])
        with self.assertRaisesRegex(ValueError, "development games"):
            flight.tune_damping(None, ["2023090702"])

    def test_paired_scores_use_identical_players_and_missing_labels(self):
        play = sample()
        play["play"]["gameId"] = "2023090702"
        # Receiver lacks adjacent input history; coverage player lacks one future label.
        prior = play["frames"][10]
        prior["entities"] = [e for e in prior["entities"] if e["id"] != "2"]
        future = play["frames"][13]
        future["entities"] = [e for e in future["entities"] if e["id"] != "3"]
        catalog = SimpleNamespace(pass_flight_source=lambda: (None, "fixture", [GAME_ID, "2023090702"]))
        development = sample()
        with patch("ftbdata.pass_window.iter_plays", side_effect=lambda release, games: iter(
            item for item in (development, play) if item["play"]["gameId"] in games
        )):
            report = flight.evaluate(catalog)
        comparison = report["comparison"]
        self.assertEqual(comparison["counts"]["pairedPlayers"], 1)
        self.assertEqual(comparison["counts"]["velocityOnlyPlayers"], 1)
        self.assertEqual(report["overall"]["samples"], 9)
        for scores in comparison["baselines"].values():
            self.assertEqual(scores["overall"]["samples"], 4)
            self.assertEqual(scores["overall"]["missingSamples"], 1)
            self.assertEqual(scores["overall"]["endpoints"], 1)
            self.assertEqual([role["role"] for role in scores["byRole"]], ["Defensive Coverage"])
        self.assertEqual(comparison["delta"], {"coordinateRmse": 0, "meanDistance": 0, "finalDistance": 0})

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
            self.assertEqual(report["fittedParameters"], 1)
            self.assertEqual(report["tuning"]["gameIds"], [GAME_ID])
            self.assertEqual(report["tuning"]["selectedRate"], 0)
            comparison = report["comparison"]
            self.assertEqual(comparison["counts"]["pairedPlayers"], 4)
            self.assertEqual(comparison["counts"]["velocityOnlyPlayers"], 0)
            for key in ("overall", "byHorizon", "byGame", "byRole"):
                self.assertEqual(comparison["baselines"][flight.VELOCITY][key], comparison["baselines"][flight.ACCELERATION][key])
                self.assertEqual(comparison["baselines"][flight.VELOCITY][key], comparison["baselines"][flight.DAMPED][key])
                self.assertEqual(comparison["baselines"][flight.VELOCITY][key], report[key])
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
            bad_tuning = copy.deepcopy(report)
            bad_tuning["tuning"]["gameIds"] = [heldout_id]
            path.write_text(json.dumps(bad_tuning))
            self.assertEqual(client.get("/flight-report").status_code, 409)
            bad_tuning = copy.deepcopy(report)
            bad_tuning["comparison"]["baselines"][flight.DAMPED]["parameters"]["dampingRate"] = 8
            path.write_text(json.dumps(bad_tuning))
            self.assertEqual(client.get("/flight-report").status_code, 409)
            bad_tuning["tuning"]["selectedRate"] = 8
            path.write_text(json.dumps(bad_tuning))
            self.assertEqual(client.get("/flight-report").status_code, 409)
            original_version = report["version"]
            report["version"] = "constant-velocity-v1"
            path.write_text(json.dumps(report))
            self.assertEqual(client.get("/flight-report").status_code, 409)
            report["version"] = original_version
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
