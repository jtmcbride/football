from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query

from .catalog import CatalogNotFoundError, PlayFilters, PlaySummary, TrackingCatalog
from .nflverse import JoinCount, JoinCoverage, camel_case


def create_app(database_path: str | Path = Path("data/db/football.duckdb")) -> FastAPI:
    catalog = TrackingCatalog(database_path)
    app = FastAPI(
        title="Football Motion Lab API",
        version="0.1.0",
        description="Local read-only access to an ingested NFL tracking catalog.",
    )

    @app.get("/health")
    def process_health() -> dict[str, Any]:
        health = catalog.data_health()
        return {"status": "ok", "catalogReady": health.ready}

    @app.get("/data-health")
    def data_health() -> dict[str, Any]:
        health = catalog.data_health()
        return {
            "ready": health.ready,
            "schemaVersion": health.schema_version,
            "sourceName": Path(health.source_root).name if health.source_root else None,
            "fingerprint": health.fingerprint,
            "ingestedAt": health.ingested_at,
            "counts": {
                "games": health.games,
                "plays": health.plays,
                "players": health.players,
                "trackingFiles": health.tracking_files,
            },
            "warnings": list(health.warnings),
            "nflverse": _coverage(health.join_coverage),
        }

    @app.get("/plays")
    def find_plays(
        season: int | None = None,
        week: int | None = Query(default=None, ge=1, le=22),
        offense: str | None = None,
        defense: str | None = None,
        down: int | None = Query(default=None, ge=1, le=4),
        play_type: Literal["pass", "rush", "other"] | None = None,
        text: str | None = Query(default=None, max_length=200),
        epa_min: float | None = None,
        epa_max: float | None = None,
        join_status: Literal["matched", "conflicting", "unmatched", "unavailable"] | None = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            result = catalog.find_plays(
                PlayFilters(
                    season=season,
                    week=week,
                    offense=offense,
                    defense=defense,
                    down=down,
                    play_type=play_type,
                    text=text,
                    epa_min=epa_min,
                    epa_max=epa_max,
                    join_status=join_status,
                ),
                page=page,
                page_size=page_size,
            )
        except CatalogNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return {
            "items": [_play_summary(item) for item in result.items],
            "page": result.page,
            "pageSize": result.page_size,
            "total": result.total,
        }

    @app.get("/plays/{game_id}/{play_id}")
    def load_play(game_id: str, play_id: str) -> dict[str, Any]:
        try:
            return catalog.load_play(game_id, play_id)
        except CatalogNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    return app


def _play_summary(summary: PlaySummary) -> dict[str, Any]:
    values = asdict(summary)
    return {
        "gameId": values["game_id"],
        "playId": values["play_id"],
        "season": values["season"],
        "week": values["week"],
        "gameDate": values["game_date"],
        "offense": values["offense"],
        "defense": values["defense"],
        "quarter": values["quarter"],
        "down": values["down"],
        "yardsToGo": values["yards_to_go"],
        "yardsGained": values["yards_gained"],
        "playType": values["play_type"],
        "description": values["description"],
        "epa": values["epa"],
        "joinStatus": values["join_status"],
    }


def _count(count: JoinCount) -> dict[str, Any]:
    return {
        "plays": count.plays,
        "matched": count.matched,
        "conflicting": count.conflicting,
        "unmatched": count.unmatched,
        "unavailable": count.unavailable,
        "matchedRate": count.matched_rate,
    }


def _coverage(coverage: JoinCoverage | None) -> dict[str, Any]:
    if coverage is None:
        return {"loaded": False, "overall": _count(JoinCount()), "seasons": [], "weeks": []}
    return {
        "loaded": coverage.loaded,
        "overall": _count(coverage.overall),
        "seasons": [
            {
                "season": item.season,
                **_count(item.counts),
                "unavailableFields": [camel_case(name) for name in item.unavailable_fields],
            }
            for item in coverage.seasons
        ],
        "weeks": [{"season": item.season, "week": item.week, **_count(item.counts)} for item in coverage.weeks],
    }


app = create_app(Path(os.environ.get("FOOTBALL_DATABASE", "data/db/football.duckdb")))
