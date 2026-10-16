"""Causal motion baselines and paired game-held-out evaluation, in yards."""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from .catalog import TrackingCatalog
    from .pass_window import Release

VERSION = "pass-flight-comparison-v3"
VELOCITY = "constant-velocity"
ACCELERATION = "constant-acceleration"
DAMPED = "damped-acceleration"
BASELINE_VERSIONS = {
    VELOCITY: "constant-velocity-v1", ACCELERATION: "constant-acceleration-v1", DAMPED: "damped-acceleration-v1",
}
DAMPING_RATES = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)
SPLIT = "sha256:pass-flight-v1:<gameId>; first 8 hex digits modulo 5 == 0"


def held_out(game_id: str) -> bool:
    return int(hashlib.sha256(f"pass-flight-v1:{game_id}".encode()).hexdigest()[:8], 16) % 5 == 0


def release_states(play: dict[str, Any], baseline: str = VELOCITY, *, damping_rate: float | None = None) -> dict[str, Any]:
    """Read only observed input frames. Selection flags are supplied by the dataset."""
    window = play["play"].get("passWindow")
    result: dict[str, Any] = {
        "version": BASELINE_VERSIONS[baseline], "baseline": baseline,
        "states": [], "unavailable": [], "reason": None,
    }
    if baseline == DAMPED:
        if damping_rate is None:
            result["reason"] = "Requires a damping rate tuned on development games."
            return result
        acceleration_weight(0, damping_rate)  # Validate the supplied parameter before exporting it.
        result["dampingRate"] = damping_rate
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
    predecessors = [f for f in before if f["frameId"] == release_id - 1]
    previous = predecessors[0] if len(predecessors) == 1 else None
    if previous and release["timeMs"] - previous["timeMs"] != 100:
        previous = None
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
        vx, vy = _velocity(entity)
        state = {
            "id": player_id, "name": player["name"], "role": player.get("role"),
            "x": entity["x"], "y": entity["y"],
            "vx": vx, "vy": vy,
        }
        if baseline in (ACCELERATION, DAMPED):
            matches = [e for e in previous["entities"] if e["id"] == player_id] if previous else []
            prior = matches[0] if len(matches) == 1 else None
            if prior is None or not all(_finite(prior.get(k)) for k in ("speed", "direction")) or prior["speed"] < 0:
                result["unavailable"].append({
                    "id": player_id, "name": player["name"],
                    "reason": "Needs one unique velocity observation exactly 0.1 s before release",
                })
                continue
            prior_vx, prior_vy = _velocity(prior)
            state.update(ax=(vx - prior_vx) / 0.1, ay=(vy - prior_vy) / 0.1)
        result["states"].append(state)
    if not selected:
        result["reason"] = "No source prediction participants."
    return result


def acceleration_weight(seconds: float, damping_rate: float = 0) -> float:
    """Double integral of exp(-rate*t), with a stable constant-acceleration limit."""
    if not _finite(damping_rate) or damping_rate < 0:
        raise ValueError("Damping rate must be finite and nonnegative")
    z = damping_rate * seconds
    if abs(z) < 0.001:
        return seconds ** 2 * (0.5 - z / 6 + z ** 2 / 24 - z ** 3 / 120 + z ** 4 / 720)
    return (z + math.expm1(-z)) / damping_rate ** 2


def project(state: dict[str, Any], seconds: float, damping_rate: float = 0) -> tuple[float, float]:
    """Freeze release velocity and optional causal acceleration; never clip or use future inputs."""
    weight = acceleration_weight(seconds, damping_rate)
    return (
        state["x"] + state["vx"] * seconds + state.get("ax", 0) * weight,
        state["y"] + state["vy"] * seconds + state.get("ay", 0) * weight,
    )


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
                x, y = project(state, seconds, forecast.get("dampingRate", 0))
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


class ScoreGroups:
    def __init__(self) -> None:
        self.total = Scores()
        self.games: dict[str, Scores] = defaultdict(Scores)
        self.roles: dict[str, Scores] = defaultdict(Scores)
        self.horizons: dict[int, Scores] = defaultdict(Scores)

    def add(self, game: str, state: dict[str, Any], step: int, error: float | None, final: bool) -> None:
        for scores in (self.total, self.games[game], self.roles[state["role"] or "Unknown"], self.horizons[step]):
            scores.add(error, final)

    def report(self) -> dict[str, Any]:
        return {
            "overall": self.total.report(),
            "byGame": [{"gameId": key, **value.report()} for key, value in sorted(self.games.items())],
            "byRole": [{"role": key, **value.report()} for key, value in sorted(self.roles.items())],
            "byHorizon": [{"seconds": key / 10, **value.report()} for key, value in sorted(self.horizons.items())],
        }


def tune_damping(release: Release, development_games: list[str]) -> dict[str, Any]:
    """Finish selection using development labels before held-out scoring begins."""
    from .pass_window import iter_plays

    game_ids = set(development_games)
    if not game_ids or any(held_out(game) for game in game_ids):
        raise ValueError("Damping must be tuned exclusively on development games")
    candidates = {rate: Scores() for rate in DAMPING_RATES}
    counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    for play in iter_plays(release, game_ids):
        if play["play"]["gameId"] not in game_ids:
            raise ValueError("Non-development play reached damping tuning")
        counts["developmentPlays"] += 1
        if play["provenance"]["validation"]["status"] == "invalid":
            skipped["invalid tracking play"] += 1
            continue
        forecast = release_states(play, ACCELERATION)
        counts["unavailablePlayers"] += len(forecast["unavailable"])
        if forecast["reason"] or not forecast["states"]:
            skipped[forecast["reason"] or "no usable acceleration inputs"] += 1
            continue
        if play["play"]["passWindow"]["arrivalFrameId"] is None:
            skipped["no observed flight window"] += 1
            continue
        counts["eligiblePlayers"] += len(forecast["states"])
        for rate, scores in candidates.items():
            for _, _, error, final in measurements(play, {**forecast, "dampingRate": rate}):
                scores.add(error, final)
        counts["scoredPlays"] += int(any(error is not None for _, _, error, _ in measurements(play, forecast)))
    if not next(iter(candidates.values())).n:
        raise ValueError("No development observations available for damping selection")
    selected = min(candidates, key=lambda rate: (candidates[rate].report()["coordinateRmse"], rate))
    return {
        "version": "damping-grid-v1", "baselineVersion": BASELINE_VERSIONS[DAMPED],
        "method": "Fixed grid search on all development games; no held-out labels used for selection",
        "objective": "minimum pooled player-frame coordinate RMSE; smallest rate wins exact ties",
        "parameter": "exponential acceleration decay rate, seconds^-1", "selectedRate": selected,
        "halfLifeSeconds": math.log(2) / selected if selected else None,
        "gameIds": sorted(game_ids), "counts": dict(counts), "skippedPlays": dict(skipped),
        "candidates": [{"rate": rate, **scores.report()} for rate, scores in candidates.items()],
        "formula": "a(t)=a0*exp(-rate*t); p(t)=p0+v0*t+a0*(rate*t+expm1(-rate*t))/rate^2; rate=0 gives constant acceleration",
    }


def evaluate(catalog: TrackingCatalog) -> dict[str, Any]:
    from .pass_window import iter_plays

    release, fingerprint, game_ids = catalog.pass_flight_source()
    holdout = sorted(game for game in game_ids if held_out(game))
    if not holdout or len(holdout) == len(game_ids):
        raise ValueError("Evaluation requires both held-out and development games under the fixed split.")
    development = sorted(set(game_ids) - set(holdout))
    tuning = tune_damping(release, development)
    tuning["fingerprint"] = fingerprint
    reference = ScoreGroups()
    paired = {baseline: ScoreGroups() for baseline in BASELINE_VERSIONS}
    comparison_counts: Counter[str] = Counter()
    unavailable_reasons: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for play in iter_plays(release, set(holdout)):
        if play["play"]["gameId"] not in holdout:
            raise ValueError("Non-held-out play reached held-out evaluation")
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
        game_id = play["play"]["gameId"]
        scored = False
        for state, step, error, final in measurements(play, forecast):
            reference.add(game_id, state, step, error, final)
            scored |= error is not None
        counts["scoredPlays"] += int(scored)
        acceleration = release_states(play, ACCELERATION)
        unavailable_reasons.update(item["reason"] for item in acceleration["unavailable"])
        common_ids = {state["id"] for state in acceleration["states"]}
        comparison_counts["pairedPlayers"] += len(common_ids)
        comparison_counts["velocityOnlyPlayers"] += len(forecast["states"]) - len(common_ids)
        comparison_counts["playsWithoutPairs"] += int(not common_ids)
        forecasts = {
            VELOCITY: {**forecast, "states": [state for state in forecast["states"] if state["id"] in common_ids]},
            ACCELERATION: acceleration,
            DAMPED: {**acceleration, "baseline": DAMPED, "version": BASELINE_VERSIONS[DAMPED],
                     "dampingRate": tuning["selectedRate"]},
        }
        for baseline, candidate in forecasts.items():
            scored = False
            for state, step, error, final in measurements(play, candidate):
                paired[baseline].add(game_id, state, step, error, final)
                scored |= error is not None
            if baseline == VELOCITY:
                comparison_counts["scoredPlays"] += int(scored)
    velocity_scores, acceleration_scores = paired[VELOCITY].total.report(), paired[ACCELERATION].total.report()
    delta = {
        metric: acceleration_scores[metric] - velocity_scores[metric]
        if acceleration_scores[metric] is not None and velocity_scores[metric] is not None else None
        for metric in ("coordinateRmse", "meanDistance", "finalDistance")
    }
    damped_scores = paired[DAMPED].total.report()
    damped_delta = {metric: damped_scores[metric] - velocity_scores[metric]
                    if damped_scores[metric] is not None and velocity_scores[metric] is not None else None for metric in delta}
    game_results: dict[str, Counter[str]] = {baseline: Counter() for baseline in (ACCELERATION, DAMPED)}
    for baseline, results in game_results.items():
        for game_id, scores in paired[VELOCITY].games.items():
            cv, other = scores.report()["coordinateRmse"], paired[baseline].games[game_id].report()["coordinateRmse"]
            if cv is not None and other is not None:
                results["improved" if other < cv else "worse" if other > cv else "tied"] += 1
    return {
        "version": VERSION, "createdAt": datetime.now(timezone.utc).isoformat(),
        "fingerprint": fingerprint, "splitRule": SPLIT,
        "heldOutGames": holdout, "developmentGames": development, "tuning": tuning,
        "fittedParameters": 1, "counts": dict(counts), "skippedPlays": dict(skipped),
        "baseline": VELOCITY, **reference.report(),
        "comparison": {
            "counts": dict(comparison_counts), "unavailableReasons": dict(unavailable_reasons),
            "baselines": {baseline: {"version": BASELINE_VERSIONS[baseline],
                                     "parameters": {"dampingRate": tuning["selectedRate"]} if baseline == DAMPED else {},
                                     **scores.report()}
                          for baseline, scores in paired.items()},
            "delta": delta, "gameResults": dict(game_results[ACCELERATION]),
            "dampedDelta": damped_delta, "dampedGameResults": dict(game_results[DAMPED]),
            "deltaDefinition": "Constant acceleration minus constant velocity on identical players, frames and labels; negative is better",
        },
        "definitions": {
            "coordinateRmse": "sqrt(sum(dx² + dy²) / (2 × observed player-frames)), yards",
            "meanDistance": "Mean Euclidean displacement error over observed player-frames, yards (frame-weighted ADE)",
            "finalDistance": "Mean Euclidean error at the last observed play output frame, yards; missing endpoints excluded",
        },
        "limitations": [
            "One damping rate selected on development games only; the two undamped baselines have no fitted parameters.",
            "Development grid scores are tuning scores, not validation scores. The rate is frozen before held-out scoring begins.",
            "Damped acceleration decays exponentially; velocity itself is not damped. Predictions remain unbounded and can leave the field.",
            "Acceleration is the backward difference of the last two input speed/direction velocity vectors, 0.1 s apart; scalar a is unused.",
            "Constant acceleration remains fixed in field coordinates, with no damping, speed cap or stopping constraint; it can reverse direction or overshoot.",
            "Comparison uses only participants with all baselines available; the top-level velocity reference retains its original eligibility.",
            "Release and arrival are derived input/output boundaries at 10 Hz, not annotated events.",
            "Output length defines only the evaluation window; landing, output positions and duration are not forecast inputs.",
            "Dataset participant selection uses future throw information. Scores describe source-selected players, not all players.",
            "Invalid plays excluded; missing labels not interpolated. Longer flights contribute more frame-weighted samples.",
            "2023 pass-window data only; no claim of generalization to other seasons or live-game forecasting.",
        ],
    }


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def report_matches(report: Any, fingerprint: str | None) -> bool:
    """Reject stale or mismatched tuning before the UI uses its fitted parameter."""
    try:
        tuning = report["tuning"]
        rate = tuning["selectedRate"]
        development, holdout = report["developmentGames"], report["heldOutGames"]
        baselines = report["comparison"]["baselines"]
        candidates = tuning["candidates"]
        if tuple(item["rate"] for item in candidates) != DAMPING_RATES or not all(
            _finite(item["coordinateRmse"]) and item["coordinateRmse"] >= 0 for item in candidates
        ):
            return False
        winner = min(candidates, key=lambda item: (item["coordinateRmse"], item["rate"]))
        return (
            bool(fingerprint) and report["version"] == VERSION and report["fingerprint"] == fingerprint
            and tuning["fingerprint"] == fingerprint and tuning["version"] == "damping-grid-v1"
            and tuning["baselineVersion"] == BASELINE_VERSIONS[DAMPED]
            and _finite(rate) and rate in DAMPING_RATES
            and winner["rate"] == rate
            and tuning["gameIds"] == development and development == sorted(set(development)) and bool(development)
            and holdout == sorted(set(holdout)) and bool(holdout)
            and not any(held_out(game) for game in development) and all(held_out(game) for game in holdout)
            and all(baselines[key]["version"] == version for key, version in BASELINE_VERSIONS.items())
            and baselines[DAMPED]["parameters"] == {"dampingRate": rate}
        )
    except (KeyError, TypeError, AttributeError):
        return False


def _velocity(entity: dict[str, Any]) -> tuple[float, float]:
    angle = math.radians(entity["direction"])
    return entity["speed"] * math.sin(angle), entity["speed"] * math.cos(angle)
