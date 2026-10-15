"""Release-only constant velocity and game-held-out evaluation, in yards."""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from .catalog import TrackingCatalog

VERSION = "constant-velocity-v1"
SPLIT = "sha256:pass-flight-v1:<gameId>; first 8 hex digits modulo 5 == 0"


def held_out(game_id: str) -> bool:
    return int(hashlib.sha256(f"pass-flight-v1:{game_id}".encode()).hexdigest()[:8], 16) % 5 == 0


def release_states(play: dict[str, Any]) -> dict[str, Any]:
    """Read only observed input frames. Selection flags are supplied by the dataset."""
    window = play["play"].get("passWindow")
    result: dict[str, Any] = {"version": VERSION, "states": [], "unavailable": [], "reason": None}
    if not window:
        result["reason"] = "Requires a pass-window release with source prediction participants."
        return result
    release_id = window["releaseFrameId"]
    before = [frame for frame in play["frames"] if frame["frameId"] <= release_id]
    selected = {e["id"]: e for frame in before for e in frame["entities"] if e.get("playerToPredict") is True}
    releases = [f for f in before if f["frameId"] == release_id]
    if len(releases) != 1 or play["play"]["normalizedDirection"] != "right":
        result["reason"] = "Release frame or normalized direction unavailable."
        return result
    release = releases[0]
    result.update(releaseFrameId=release_id, releaseTimeMs=release["timeMs"])
    for player_id, player in selected.items():
        matches = [e for e in release["entities"] if e["id"] == player_id]
        reason = None
        entity = matches[0] if len(matches) == 1 else None
        if entity is None:
            reason = "Missing or duplicate release position"
        elif not all(_finite(entity.get(k)) for k in ("x", "y", "speed", "direction")) or entity["speed"] < 0:
            reason = "Release position, speed, or movement direction unavailable"
        if reason:
            result["unavailable"].append({"id": player_id, "name": player["name"], "reason": reason})
            continue
        angle = math.radians(entity["direction"])
        result["states"].append({
            "id": player_id, "name": player["name"], "role": player.get("role"),
            "x": entity["x"], "y": entity["y"],
            "vx": entity["speed"] * math.sin(angle), "vy": entity["speed"] * math.cos(angle),
        })
    if not selected:
        result["reason"] = "No source prediction participants."
    return result


def project(state: dict[str, Any], seconds: float) -> tuple[float, float]:
    """No clipping, acceleration, landing point, outcome, or future position inputs."""
    return state["x"] + state["vx"] * seconds, state["y"] + state["vy"] * seconds


def measurements(
    play: dict[str, Any], forecast: dict[str, Any]
) -> Iterator[tuple[dict[str, Any], int, float | None, bool]]:
    """Observed labels are accessed only here, after constructing the forecast."""
    if forecast["reason"]:
        return
    release_id = forecast["releaseFrameId"]
    arrival_id = play["play"]["passWindow"]["arrivalFrameId"]
    if arrival_id is None:
        return
    frames = {frame["frameId"]: frame for frame in play["frames"]}
    for frame_id in range(release_id + 1, arrival_id + 1):
        seconds = (frame_id - release_id) / 10
        entities = frames.get(frame_id, {}).get("entities", [])
        for state in forecast["states"]:
            matches = [e for e in entities if e["id"] == state["id"]]
            actual = matches[0] if len(matches) == 1 else None
            error = None
            if actual and all(_finite(actual.get(k)) for k in ("x", "y")):
                x, y = project(state, seconds)
                error = math.hypot(x - actual["x"], y - actual["y"])
            yield state, frame_id - release_id, error, frame_id == arrival_id


class Scores:
    def __init__(self) -> None:
        self.n = self.missing = self.final_n = 0
        self.distance = self.squared = self.final = 0.0

    def add(self, error: float | None, final: bool) -> None:
        if error is None:
            self.missing += 1
            return
        self.n += 1
        self.distance += error
        self.squared += error * error
        if final:
            self.final_n += 1
            self.final += error

    def report(self) -> dict[str, int | float | None]:
        return {
            "samples": self.n, "missingSamples": self.missing, "endpoints": self.final_n,
            "coordinateRmse": math.sqrt(self.squared / (2 * self.n)) if self.n else None,
            "meanDistance": self.distance / self.n if self.n else None,
            "finalDistance": self.final / self.final_n if self.final_n else None,
        }


def evaluate(catalog: TrackingCatalog) -> dict[str, Any]:
    from .pass_window import iter_plays

    release, fingerprint, game_ids = catalog.pass_flight_source()
    holdout = sorted(game for game in game_ids if held_out(game))
    if not holdout or len(holdout) == len(game_ids):
        raise ValueError("Evaluation requires both held-out and development games under the fixed split.")
    total = Scores()
    games, roles, horizons = defaultdict(Scores), defaultdict(Scores), defaultdict(Scores)
    skipped: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for play in iter_plays(release, set(holdout)):
        counts["heldOutPlays"] += 1
        if play["provenance"]["validation"]["status"] == "invalid":
            skipped["invalid tracking play"] += 1
            continue
        forecast = release_states(play)
        if forecast["reason"]:
            skipped[forecast["reason"]] += 1
            continue
        counts["unavailablePlayers"] += len(forecast["unavailable"])
        if play["play"]["passWindow"]["arrivalFrameId"] is None:
            skipped["no observed flight window"] += 1
            continue
        counts["eligiblePlayers"] += len(forecast["states"])
        scored = False
        for state, step, error, final in measurements(play, forecast):
            for scores in (total, games[play["play"]["gameId"]], roles[state["role"] or "Unknown"], horizons[step]):
                scores.add(error, final)
            scored |= error is not None
        counts["scoredPlays"] += int(scored)
    return {
        "version": VERSION, "createdAt": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint, "splitRule": SPLIT,
        "heldOutGames": holdout, "developmentGames": sorted(set(game_ids) - set(holdout)),
        "fittedParameters": 0, "counts": dict(counts), "skippedPlays": dict(skipped),
        "overall": total.report(),
        "byGame": [{"gameId": key, **value.report()} for key, value in sorted(games.items())],
        "byRole": [{"role": key, **value.report()} for key, value in sorted(roles.items())],
        "byHorizon": [{"seconds": key / 10, **value.report()} for key, value in sorted(horizons.items())],
        "definitions": {
            "coordinateRmse": "sqrt(sum(dx² + dy²) / (2 × observed player-frames)), yards",
            "meanDistance": "Mean Euclidean displacement error over observed player-frames, yards (frame-weighted ADE)",
            "finalDistance": "Mean Euclidean error at the last observed play output frame, yards; missing endpoints excluded",
        },
        "limitations": [
            "No fitted parameters. Development games are reserved for future models; none are used to fit this baseline.",
            "Release and arrival are derived input/output boundaries at 10 Hz, not annotated events.",
            "Output length defines only the evaluation window; landing, output positions and duration are not forecast inputs.",
            "Dataset participant selection uses future throw information. Scores describe source-selected players, not all players.",
            "Invalid plays excluded; missing labels not interpolated. Longer flights contribute more frame-weighted samples.",
            "2023 pass-window data only; no claim of generalization to other seasons or live-game forecasting.",
        ],
    }


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)
