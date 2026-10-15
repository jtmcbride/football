from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query

from .catalog import CatalogNotFoundError, PlayFilters, PlaySummary, TrackingCatalog
from .nflverse import JoinCount, JoinCoverage, camel_case
from .quality import QualityCount, QualityReport


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
            "quality": _quality(health.quality),
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
        quality_status: Literal["valid", "incomplete", "invalid", "unassessed"] | None = None,
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
                    quality_status=quality_status,
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

    @app.get("/routes")
    def find_routes(
        route: str | None = Query(default=None, max_length=80),
        coverage: str | None = Query(default=None, max_length=80),
        coverage_type: str | None = Query(default=None, max_length=80),
        game_id: str | None = Query(default=None, max_length=30),
        play_id: str | None = Query(default=None, max_length=30),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=8, ge=1, le=50),
    ) -> dict[str, Any]:
        if (game_id is None) != (play_id is None):
            raise HTTPException(status_code=422, detail="Supply both game_id and play_id for similarity search")
        try:
            return catalog.find_routes(
                route=route, coverage=coverage, coverage_type=coverage_type,
                reference=(game_id, play_id) if game_id is not None else None,
                page=page, page_size=page_size,
            )
        except CatalogNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

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
        "qualityStatus": values["quality_status"],
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


def _quality_count(count: QualityCount) -> dict[str, Any]:
    return {
        "plays": count.plays,
        "valid": count.valid,
        "incomplete": count.incomplete,
        "invalid": count.invalid,
        "validRate": count.valid_rate,
    }


def _quality(report: QualityReport | None) -> dict[str, Any]:
    if report is None:
        report = QualityReport(version=0, assessed_at=None, overall=QualityCount())
    return {
        "version": report.version,
        "assessedAt": report.assessed_at,
        "overall": _quality_count(report.overall),
        "checks": [{"id": item.id, **item.counts} for item in report.checks],
        "seasons": [{"season": item.season, **_quality_count(item.counts)} for item in report.seasons],
        "weeks": [{"season": item.season, "week": item.week, **_quality_count(item.counts)} for item in report.weeks],
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
