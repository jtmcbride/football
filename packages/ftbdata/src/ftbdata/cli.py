from __future__ import annotations

import argparse
from pathlib import Path

from .tracking import extract_play, make_demo_play, write_play


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="football", description="NFL tracking-data utilities")
    commands = root.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="Extract one Big Data Bowl play to web JSON")
    extract.add_argument("--tracking", type=Path, required=True)
    extract.add_argument("--plays", type=Path)
    extract.add_argument("--players", type=Path)
    extract.add_argument("--game-id", required=True)
    extract.add_argument("--play-id", required=True)
    extract.add_argument("--output", type=Path, required=True)

    demo = commands.add_parser("demo", help="Generate the schematic zero-setup play")
    demo.add_argument("--output", type=Path, required=True)
    demo.add_argument("--frames", type=int, default=64)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "demo":
        play = make_demo_play(args.frames)
    else:
        play = extract_play(
            args.tracking,
            args.game_id,
            args.play_id,
            plays_path=args.plays,
            players_path=args.players,
        )
    write_play(play, args.output)
    print(f"Wrote {len(play['frames'])} frames to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
