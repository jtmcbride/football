# Football Motion Lab

A local-first NFL tracking analysis workbench: animate one play at 10 Hz, inspect
players frame by frame, and measure spacing without losing sight of where the
data came from.

The first vertical slice is intentionally narrow. It handles NFL Big Data Bowl
tracking exports, normalizes every play so the offense moves left-to-right, and
renders a fast custom-SVG replay with player inspection and spatial summaries.

## What works now

- Animated all-22 + football field replay
- Frame scrubbing, event jumps, and 0.5× / 1× / 2× playback
- Player labels, recent movement trails, and facing-direction overlays
- Per-frame speed, acceleration, location, matchup separation, and formation width
- Big Data Bowl CSV → compact play JSON extraction
- Correct 180° normalization of leftward plays, including `x`, `y`, `dir`, and `o`
- A clearly labeled schematic demo for immediate use

The bundled play is generated, not an NFL play. Kaggle requires users to sign in
and accept the Big Data Bowl competition rules, so this repository does not
redistribute the raw competition files.

## Quick start

Requires Python 3.11+ and Node 20.19+.

```bash
make setup
make demo
make dev
```

Open the Vite URL (normally <http://localhost:5173>).

## Load public tracking data

1. Join an NFL Big Data Bowl competition on Kaggle and accept its rules.
2. Download and unzip `tracking_week_*.csv`, `plays.csv`, and `players.csv`.
3. Extract one play:

```bash
uv run football extract \
  --tracking data/raw/tracking_week_1.csv \
  --plays data/raw/plays.csv \
  --players data/raw/players.csv \
  --game-id 2022090800 \
  --play-id 56 \
  --output data/exports/2022090800-56.json
```

Use **Open play JSON** in the app and select that export. The extractor streams
the week CSV and retains only the selected play, so memory use does not scale
with the full tracking file.

The 2025 Big Data Bowl field contract is documented on the
[official Kaggle data page](https://www.kaggle.com/competitions/nfl-big-data-bowl-2025/data).
It provides game, play, player, player-play, and weekly tracking CSVs. Tracking
rows contain `gameId`, `playId`, `nflId`, `frameId`, `x`, `y`, `s`, `a`, `dir`,
`o`, `event`, and `playDirection`; a missing `nflId` identifies the football.

## Data sources and boundaries

| Source | Best use here | Access and terms |
|---|---|---|
| NFL Big Data Bowl | Player and football coordinates, speed, acceleration, orientation, tagged events | Public after Kaggle sign-in and acceptance; subject to competition rules |
| nflverse | Play-by-play context, EPA/WPA, rosters, schedules, participation | GitHub releases in CSV, Parquet, RDS, and other formats; repository metadata is CC BY 4.0 |

Big Data Bowl coverage is a selected release, not a continuous public archive of
every NFL game. Do not describe a model trained on one release as league-wide
without evaluating the release's seasons, weeks, play filters, and competition
task.

The Big Data Bowl keys can be joined to nflverse play-by-play using `gameId` ↔
`old_game_id` and `playId` ↔ `play_id`, as noted in the official competition
documentation.

## Architecture

```text
packages/ftbdata   streaming CSV ingest, coordinate normalization, JSON export
apps/web           React + TypeScript, custom SVG field and analysis UI
data/raw           user-downloaded source files (gitignored)
data/exports       extracted play JSON (gitignored)
```

This mirrors the baseball project's local-first shape while keeping the first
slice dependency-light. The play JSON is a deliberate seam: the visualization
does not need to know whether a later backend uses CSV, Parquet, DuckDB, or an
API.

## Tests

```bash
make test
make web-build
```

The Python tests cover frame ordering, ball handling, player metadata, and
leftward-play rotation. The web tests cover derived spatial metrics and event
labels; typechecking and the production build catch the integration surface.

## Next useful slices

1. Add a DuckDB catalog of available games and plays rather than opening one JSON file.
2. Join nflverse EPA/down-distance context and add filters for team, concept, coverage, and result.
3. Derive route geometry, defender leverage, pocket shape, and separation-over-time curves.
4. Add reliability/provenance badges so derived metrics always disclose coverage and missing fields.
5. Train only after establishing season/game splits that prevent play-family and team leakage.
