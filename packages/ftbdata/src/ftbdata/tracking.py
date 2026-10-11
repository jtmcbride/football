from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

FIELD_LENGTH = 120.0
FIELD_WIDTH = 53.3


def _number(value: str | None, *, integer: bool = False) -> float | int | None:
    if value is None or value.strip() == "":
        return None
    return int(float(value)) if integer else round(float(value), 4)


def _rotate_angle(value: float | int | None) -> float | None:
    return None if value is None else round((float(value) + 180.0) % 360.0, 3)


def _read_lookup(path: Path | None, key_fields: tuple[str, ...]) -> dict[tuple[str, ...], dict[str, str]]:
    if path is None:
        return {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {
            tuple(row[field] for field in key_fields): row
            for row in csv.DictReader(handle)
        }


def _first_nonempty(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def extract_play(
    tracking_path: str | Path,
    game_id: str | int,
    play_id: str | int,
    *,
    plays_path: str | Path | None = None,
    players_path: str | Path | None = None,
) -> dict[str, Any]:
    """Extract one play from a Big Data Bowl tracking CSV.

    Coordinates are rotated 180 degrees when necessary so the offense always
    travels left-to-right. The original play direction remains in metadata.
    """

    game_key, play_key = str(game_id), str(play_id)
    play_lookup = _read_lookup(Path(plays_path) if plays_path else None, ("gameId", "playId"))
    player_lookup = _read_lookup(Path(players_path) if players_path else None, ("nflId",))
    play_row = play_lookup.get((game_key, play_key), {})

    frame_rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    event_by_frame: dict[int, str] = {}
    source_direction: str | None = None
    offense = _first_nonempty(play_row, "possessionTeam")
    defense = _first_nonempty(play_row, "defensiveTeam")

    with Path(tracking_path).open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            if row.get("gameId") != game_key or row.get("playId") != play_key:
                continue

            frame_id = int(row["frameId"])
            source_direction = source_direction or row.get("playDirection", "right").lower()
            rotate = source_direction == "left"
            nfl_id = _number(row.get("nflId"), integer=True)
            is_ball = nfl_id is None
            club = row.get("club") or ("football" if is_ball else "unknown")
            player = player_lookup.get((str(nfl_id),), {}) if nfl_id is not None else {}
            x = float(row["x"])
            y = float(row["y"])
            orientation = _number(row.get("o"))
            direction = _number(row.get("dir"))
            if rotate:
                x = FIELD_LENGTH - x
                y = FIELD_WIDTH - y
                orientation = _rotate_angle(orientation)
                direction = _rotate_angle(direction)

            entity = {
                "id": "ball" if is_ball else str(nfl_id),
                "kind": "ball" if is_ball else "player",
                "name": row.get("displayName") or player.get("displayName") or "Football",
                "club": club,
                "position": player.get("position") or None,
                "jersey": _number(row.get("jerseyNumber"), integer=True),
                "x": round(x, 3),
                "y": round(y, 3),
                "speed": _number(row.get("s")) or 0.0,
                "acceleration": _number(row.get("a")) or 0.0,
                "orientation": orientation,
                "direction": direction,
            }
            frame_rows[frame_id].append(entity)
            event = (row.get("event") or "").strip()
            if event and event != "None":
                event_by_frame[frame_id] = event

    if not frame_rows:
        raise ValueError(f"No tracking rows found for gameId={game_key}, playId={play_key}")

    frame_ids = sorted(frame_rows)
    absolute_yardline = _number(play_row.get("absoluteYardlineNumber"))
    if source_direction == "left" and absolute_yardline is not None:
        absolute_yardline = round(FIELD_LENGTH - float(absolute_yardline), 3)
    frames = [
        {
            "frameId": frame_id,
            "timeMs": index * 100,
            "event": event_by_frame.get(frame_id) or None,
            "entities": sorted(frame_rows[frame_id], key=lambda item: (item["kind"] != "ball", item["id"])),
        }
        for index, frame_id in enumerate(frame_ids)
    ]

    return {
        "schemaVersion": 1,
        "source": {
            "name": "NFL Big Data Bowl",
            "kind": "public-competition-data",
            "trackingFile": Path(tracking_path).name,
        },
        "field": {"length": FIELD_LENGTH, "width": FIELD_WIDTH, "endZoneDepth": 10.0},
        "play": {
            "gameId": game_key,
            "playId": play_key,
            "title": _play_title(play_row, game_key, play_key),
            "description": _first_nonempty(play_row, "playDescription") or "Tracking play",
            "offense": offense,
            "defense": defense,
            "quarter": _number(play_row.get("quarter"), integer=True),
            "down": _number(play_row.get("down"), integer=True),
            "yardsToGo": _number(play_row.get("yardsToGo")),
            "yardsGained": _number(play_row.get("yardsGained")),
            "absoluteYardline": absolute_yardline,
            "originalDirection": source_direction or "right",
            "normalizedDirection": "right",
        },
        "frames": frames,
    }


def _play_title(row: dict[str, str], game_id: str, play_id: str) -> str:
    offense = _first_nonempty(row, "possessionTeam")
    defense = _first_nonempty(row, "defensiveTeam")
    if offense and defense:
        return f"{offense} vs {defense}"
    return f"Game {game_id} / Play {play_id}"


def make_demo_play(frame_count: int = 64) -> dict[str, Any]:
    """Create an unmistakably schematic play for zero-setup UI exploration."""

    frames: list[dict[str, Any]] = []

    for frame in range(frame_count):
        t = frame / 10.0
        snapped = frame >= 10
        action_t = max(0.0, t - 1.0)
        entities: list[dict[str, Any]] = []

        offense_starts = [
            ("QB", 31.5, 26.65), ("RB", 27.8, 30.0), ("LT", 34.2, 21.0),
            ("LG", 34.2, 23.3), ("C", 34.2, 26.65), ("RG", 34.2, 30.0),
            ("RT", 34.2, 32.3), ("X", 34.0, 5.0), ("H", 33.0, 39.0),
            ("Y", 33.5, 35.0), ("Z", 34.0, 49.0),
        ]
        for index, (name, x0, y0) in enumerate(offense_starts):
            x, y = _demo_offense_position(name, x0, y0, action_t)
            speed = 0.0 if not snapped else min(8.6, math.hypot(x - x0, y - y0) / max(action_t, 0.15))
            entities.append(_demo_entity(name, "player", "SEA", index + 1, x, y, speed, 90.0))

        defense_starts = [
            ("DE1", 36.0, 19.5), ("DT1", 35.7, 23.0), ("NT", 35.7, 26.65),
            ("DT2", 35.7, 30.3), ("DE2", 36.0, 33.7), ("LB1", 39.5, 23.5),
            ("LB2", 39.5, 30.0), ("NB", 39.0, 38.0), ("CB1", 39.5, 6.0),
            ("S", 46.0, 27.0), ("CB2", 39.5, 48.0),
        ]
        for index, (name, x0, y0) in enumerate(defense_starts):
            x, y = _demo_defense_position(name, x0, y0, action_t)
            speed = 0.0 if not snapped else min(8.3, math.hypot(x - x0, y - y0) / max(action_t, 0.15))
            entities.append(_demo_entity(name, "player", "DEN", index + 20, x, y, speed, 270.0))

        if frame < 10:
            bx, by = 34.35, 26.65
        elif frame < 36:
            bx = 33.9 - action_t * 1.05
            by = 26.65 + math.sin(action_t * 1.2) * 0.15
        else:
            flight = (frame - 36) / 10.0
            bx = 31.2 + flight * 15.5
            by = 26.75 - flight * 8.2
        entities.append(_demo_entity("Football", "ball", "football", None, bx, by, 0.0, None))

        event = None
        if frame == 10:
            event = "ball_snap"
        elif frame == 36:
            event = "pass_forward"
        elif frame == 57:
            event = "pass_arrived"
        frames.append({"frameId": frame + 1, "timeMs": frame * 100, "event": event, "entities": entities})

    return {
        "schemaVersion": 1,
        "source": {"name": "Schematic demo", "kind": "generated-demo", "trackingFile": None},
        "field": {"length": FIELD_LENGTH, "width": FIELD_WIDTH, "endZoneDepth": 10.0},
        "play": {
            "gameId": "demo",
            "playId": "mesh-01",
            "title": "SEA vs DEN",
            "description": "Schematic mesh concept. Load an extracted Big Data Bowl play for real tracking.",
            "offense": "SEA",
            "defense": "DEN",
            "quarter": 2,
            "down": 3,
            "yardsToGo": 7,
            "yardsGained": None,
            "absoluteYardline": 34.0,
            "originalDirection": "right",
            "normalizedDirection": "right",
        },
        "frames": frames,
    }


def _demo_offense_position(name: str, x: float, y: float, t: float) -> tuple[float, float]:
    if name == "QB":
        return x - min(t, 2.2) * 1.35, y
    if name == "RB":
        return x + min(t, 2.0) * 2.2, y + min(t, 2.0) * 2.3
    if name in {"LT", "LG", "C", "RG", "RT"}:
        direction = {"LT": -0.5, "LG": -0.2, "C": 0.0, "RG": 0.25, "RT": 0.55}[name]
        return x + min(t, 1.2) * 0.8, y + direction * min(t, 2.0)
    if name == "X":
        return x + min(t, 3.8) * 5.9, y + min(t, 2.4) * 1.0
    if name == "Z":
        return x + min(t, 4.0) * 5.5, y - min(t, 3.2) * 1.1
    if name == "Y":
        return x + min(t, 2.2) * 4.8, y - min(t, 2.2) * 4.0
    return x + min(t, 2.0) * 5.0, y - min(t, 2.2) * 5.0


def _demo_defense_position(name: str, x: float, y: float, t: float) -> tuple[float, float]:
    if name.startswith(("DE", "DT")) or name == "NT":
        return x - min(t, 2.5) * 1.7, y + math.sin(t * 1.7) * 0.35
    if name.startswith("CB"):
        sign = 1 if y < FIELD_WIDTH / 2 else -1
        return x + min(t, 3.5) * 4.3, y + sign * min(t, 2.0) * 0.8
    if name == "S":
        return x + min(t, 2.2) * 1.1, y - min(t, 3.0) * 1.2
    return x + min(t, 2.0) * 1.3, y + math.sin(t) * 1.2


def _demo_entity(
    name: str,
    kind: str,
    club: str,
    jersey: int | None,
    x: float,
    y: float,
    speed: float,
    orientation: float | None,
) -> dict[str, Any]:
    return {
        "id": "ball" if kind == "ball" else name,
        "kind": kind,
        "name": name,
        "club": club,
        "position": name if kind == "player" else None,
        "jersey": jersey,
        "x": round(x, 3),
        "y": round(y, 3),
        "speed": round(speed, 3),
        "acceleration": 0.0,
        "orientation": orientation,
        "direction": orientation,
    }


def write_play(play: dict[str, Any], output: str | Path) -> None:
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(play, indent=2) + "\n", encoding="utf-8")
