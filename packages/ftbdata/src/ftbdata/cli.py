from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .catalog import CatalogError, CatalogValidationError, PlayFilters, TrackingCatalog
from .nflverse import JOIN_STATUSES
from .quality import PLAY_STATUSES
from .tracking import extract_play, make_demo_play, write_play


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="football", description="NFL tracking-data utilities")
    commands = root.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="Extract one Big Data Bowl play to web JSON")
    extract.add_argument("--tracking", type=Path, required=True)
    extract.add_argument("--plays", type=Path)
    extract.add_argument("--players", type=Path)
    extract.add_argument("--games", type=Path)
    extract.add_argument("--game-id", required=True)
    extract.add_argument("--play-id", required=True)
    extract.add_argument("--output", type=Path, required=True)

    demo = commands.add_parser("demo", help="Generate the schematic zero-setup play")
    demo.add_argument("--output", type=Path, required=True)
    demo.add_argument("--frames", type=int, default=64)

    ingest = commands.add_parser("ingest", help="Catalog a downloaded public-data release")
    ingest_sources = ingest.add_subparsers(dest="source", required=True)
    ingest_bdb = ingest_sources.add_parser("bdb", help="Catalog an NFL Big Data Bowl release")
    ingest_bdb.add_argument("--input", type=Path, required=True, help="Unzipped competition directory")
    ingest_bdb.add_argument("--database", type=Path, default=Path("data/db/football.duckdb"))
    ingest_nflverse = ingest_sources.add_parser(
        "nflverse", help="Join nflverse play-by-play (play_by_play_<season>.parquet) to the catalog"
    )
    ingest_nflverse.add_argument("--input", type=Path, required=True, help="Directory of play-by-play Parquet files")
    ingest_nflverse.add_argument("--database", type=Path, default=Path("data/db/football.duckdb"))

    plays = commands.add_parser("plays", help="Search plays in a local tracking catalog")
    plays.add_argument("--database", type=Path, default=Path("data/db/football.duckdb"))
    plays.add_argument("--season", type=int)
    plays.add_argument("--week", type=int)
    plays.add_argument("--offense")
    plays.add_argument("--defense")
    plays.add_argument("--down", type=int)
    plays.add_argument("--play-type", choices=("pass", "rush", "other"))
    plays.add_argument("--text")
    plays.add_argument("--epa-min", type=float)
    plays.add_argument("--epa-max", type=float)
    plays.add_argument("--join-status", choices=JOIN_STATUSES)
    plays.add_argument("--quality-status", choices=(*PLAY_STATUSES, "unassessed"))
    plays.add_argument("--page", type=int, default=1)
    plays.add_argument("--page-size", type=int, default=50)

    health = commands.add_parser("health", help="Report local tracking-catalog readiness")
    health.add_argument("--database", type=Path, default=Path("data/db/football.duckdb"))

    quality = commands.add_parser(
        "quality", help="Emit the machine-readable tracking-quality report for a local catalog"
    )
    quality.add_argument("--database", type=Path, default=Path("data/db/football.duckdb"))
    quality.add_argument(
        "--status",
        action="append",
        choices=PLAY_STATUSES,
        help="List per-play findings for plays with this status (repeatable; default: incomplete and invalid)",
    )
    quality.add_argument("--summary-only", action="store_true", help="Omit the per-play findings")

    export = commands.add_parser("export", help="Export one cataloged play to web JSON")
    export.add_argument("--database", type=Path, default=Path("data/db/football.duckdb"))
    export.add_argument("--game-id", required=True)
    export.add_argument("--play-id", required=True)
    export.add_argument("--output", type=Path, required=True)

    serve = commands.add_parser("serve", help="Serve the local read-only tracking API")
    serve.add_argument("--database", type=Path, default=Path("data/db/football.duckdb"))
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--flight-report", type=Path, help="Held-out evaluation JSON to show in the prediction lab")
    evaluate = commands.add_parser("evaluate-flight", help="Measure constant velocity on a fixed game holdout")
    evaluate.add_argument("--database", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(create_app(args.database, flight_report=args.flight_report), host=args.host, port=args.port)
            return 0
        if args.command == "evaluate-flight":
            from .flight import evaluate

            report = evaluate(TrackingCatalog(args.database))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            print(json.dumps({"output": str(args.output), "counts": report["counts"], "overall": report["overall"]}, indent=2))
            return 0
        if args.command == "ingest":
            catalog = TrackingCatalog(args.database)
            report = (
                catalog.ingest_nflverse(args.input) if args.source == "nflverse" else catalog.ingest_release(args.input)
            )
            print(json.dumps(asdict(report), indent=2))
            return 0
        if args.command == "plays":
            page = TrackingCatalog(args.database).find_plays(
                PlayFilters(
                    season=args.season,
                    week=args.week,
                    offense=args.offense,
                    defense=args.defense,
                    down=args.down,
                    play_type=args.play_type,
                    text=args.text,
                    epa_min=args.epa_min,
                    epa_max=args.epa_max,
                    join_status=args.join_status,
                    quality_status=args.quality_status,
                ),
                page=args.page,
                page_size=args.page_size,
            )
            print(json.dumps(asdict(page), indent=2))
            return 0
        if args.command == "health":
            health = TrackingCatalog(args.database).data_health()
            print(json.dumps(asdict(health), indent=2))
            return 0 if health.ready else 1
        if args.command == "quality":
            catalog = TrackingCatalog(args.database)
            report = {"report": asdict(catalog.quality_report())}
            if not args.summary_only:
                report["plays"] = list(catalog.play_quality(tuple(args.status or ("incomplete", "invalid"))))
            print(json.dumps(report, indent=2))
            return 0
        if args.command == "export":
            play = TrackingCatalog(args.database).load_play(args.game_id, args.play_id)
            write_play(play, args.output)
            print(f"Wrote {len(play['frames'])} frames to {args.output}")
            return 0
        if args.command == "demo":
            play = make_demo_play(args.frames)
        else:
            play = extract_play(
                args.tracking,
                args.game_id,
                args.play_id,
                plays_path=args.plays,
                players_path=args.players,
                games_path=args.games,
            )
        write_play(play, args.output)
        print(f"Wrote {len(play['frames'])} frames to {args.output}")
        return 0
    except CatalogValidationError as error:
        print(json.dumps({"status": "invalid", "errors": error.errors}, indent=2), file=sys.stderr)
        return 2
    except (CatalogError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
