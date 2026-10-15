"""Compact, release-relative target routes for descriptive geometric search.

Only observed pre-throw coordinates enter the signature. Time is resampled to
21 equal fractions of that window; duration is reported, not used in ranking.
No lateral mirroring, scaling of distances, outcome labels, or flight positions.
"""

from __future__ import annotations

import math
from typing import Any

SAMPLE_COUNT = 21


def describe(play: dict[str, Any]) -> dict[str, Any] | None:
    context = play["play"]
    window = context.get("passWindow")
    if not window or context["normalizedDirection"] != "right":
        return None
    target = window["targetReceiverId"]
    if not target:
        return None
    frames = [frame for frame in play["frames"] if frame["frameId"] <= window["releaseFrameId"]]
    if len(frames) < 2 or frames[-1]["frameId"] != window["releaseFrameId"]:
        return None
    points = []
    receiver = None
    for index, frame in enumerate(frames):
        entities = [entity for entity in frame["entities"] if entity["id"] == target]
        if len(entities) != 1:
            return None
        if index and (frame["frameId"] != frames[index - 1]["frameId"] + 1
                      or frame["timeMs"] - frames[index - 1]["timeMs"] != 100):
            return None
        receiver = entities[0]
        if not all(math.isfinite(receiver[key]) for key in ("x", "y")):
            return None
        points.append((receiver["x"], receiver["y"]))
    release_x, release_y = points[-1]
    sampled = []
    for index in range(SAMPLE_COUNT):
        position = index * (len(points) - 1) / (SAMPLE_COUNT - 1)
        lower = int(position)
        upper = min(lower + 1, len(points) - 1)
        fraction = position - lower
        x, y = points[lower]
        end_x, end_y = points[upper]
        sampled.append({
            "x": round(x + (end_x - x) * fraction - release_x, 3),
            "y": round(y + (end_y - y) * fraction - release_y, 3),
        })
    landing = context.get("ballLanding")
    return {
        "gameId": context["gameId"], "playId": context["playId"],
        "receiverId": target, "receiverName": receiver["name"],
        "offense": context["offense"], "defense": context["defense"],
        "route": window["route"], "coverage": window["coverage"], "coverageType": window["coverageType"],
        "observedSeconds": round((frames[-1]["timeMs"] - frames[0]["timeMs"]) / 1000, 3),
        "release": {"x": release_x, "y": release_y},
        "points": sampled,
        "ballLanding": {"x": round(landing["x"] - release_x, 3),
                        "y": round(landing["y"] - release_y, 3)} if landing else None,
    }


def signature(route: dict[str, Any]) -> list[float]:
    return [point[axis] for point in route["points"] for axis in ("x", "y")]
