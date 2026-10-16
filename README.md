# Football Motion Lab

A local-first NFL tracking analysis workbench: animate one play at 10 Hz, inspect
players frame by frame, and measure spacing without losing sight of where the
data came from.

![Football Motion Lab replaying the official NFL tracking sample](artifacts/football-motion-lab.png)

The first vertical slice is intentionally narrow. It handles NFL Big Data Bowl
tracking exports, normalizes every play so the offense moves left-to-right, and
renders a fast custom-SVG replay with player inspection and spatial summaries.

## What works now

- Animated all-22 + football field replay
- Frame scrubbing, event jumps, and 0.5× / 1× / 2× playback
- Player labels, recent movement trails, and facing-direction overlays
- Linked selected-player speed and nearest-opponent separation charts
- Snap-relative route depth, lateral movement, displacement, and event markers
- Team centroids, RMS spatial spread, quarterback depth, and protection-envelope overlays
- Route atlas with targeted-receiver and coverage filters, geometric similarity search, and up to three comparison overlays
- Recorded pass landing points and explicit pre-throw / in-flight boundaries for 2026 plays
- Explicit unavailable states for source fields such as 2017 acceleration and orientation
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
make sample  # optional: ingest the official 2017 sample and open a real play
make dev
```

Open the Vite URL (normally <http://localhost:5173>).

## Load public tracking data

1. Join an NFL Big Data Bowl competition on Kaggle and accept its rules.
2. Download and unzip `tracking_week_*.csv`, `plays.csv`, and `players.csv`.
3. Build the local catalog:

```bash
uv run football ingest bdb \
  --input data/raw/nfl-big-data-bowl-2025 \
  --database data/db/football.duckdb

uv run football health
uv run football plays --season 2022 --week 1 --offense BUF --play-type pass
```

The catalog validates the release, records a content fingerprint, and indexes
games, plays, players, and weekly tracking-file locations in DuckDB. It leaves
the large tracking CSVs in place rather than duplicating them. Re-ingesting an
unchanged release is idempotent.

### Tracking quality and provenance

Ingest also streams every tracking file once and assesses each play (field bounds,
frame order, 10 Hz cadence, player identity, football coverage, event order, entity
count, direction normalization, and more). Expect a few minutes for a full release.
The ingest output includes a machine-readable `quality` summary; to re-emit it later,
or to list every play that is not valid with its findings:

```bash
uv run football quality --database data/db/football.duckdb
uv run football quality --status invalid --summary-only
uv run football plays --quality-status incomplete
```

Plays are graded `valid`, `incomplete` (usable but missing or suspect data),
`invalid` (corrupt), or `generated` (the demo). Every served play carries a
`provenance` block (release, files, software version, direction handling, available
and missing source fields, nflverse join status, and the full check results), and the
web app shows it beside the replay. Fields a source never provides, such as
acceleration in the legacy 2017 sample, are disclosed but do not make a play
incomplete.

The thresholds have been checked against the NFL's official 2017 single-game
sample. Of 177 plays, 169 are valid, eight are incomplete, and none are invalid.
The eight warnings are attributable to brief source-coordinate dropouts, one
21-player play, one direction that cannot be inferred at midfield, and one event
alignment inconsistency. This validation does not establish league-wide behavior:
the sample contains one game, omits acceleration and orientation, and cannot
independently cross-check the yard line because legacy direction is inferred from
the ball and line of scrimmage.

### Add nflverse play-by-play context

Download `play_by_play_<season>.parquet` for the seasons in your catalog from the
[nflverse-data `pbp` release](https://github.com/nflverse/nflverse-data/releases/tag/pbp)
into their own directory, then join them:

```bash
uv run football ingest nflverse --input data/raw/nflverse-pbp
uv run football plays --join-status unmatched
uv run football plays --epa-min 1.0
```

Big Data Bowl `gameId`/`playId` are joined to nflverse `old_game_id`/`play_id`
within the same season. Nothing is dropped when a join fails: each tracking play
reports `matched`, `conflicting` (joined but quarter or down disagrees),
`unmatched` (season loaded, no row), or `unavailable` (no file for that season).
The ingest report and `GET /data-health` give measured coverage by season and
week, plus fields a season's file does not contain at all (for example formation
and personnel before 2020). nflverse rows live in separate DuckDB tables, so
re-ingesting tracking never discards them. EPA and WPA are nflverse model
outputs, not tracking measurements.

To export a cataloged play for the current file-opening workflow, use:

```bash
uv run football export \
  --database data/db/football.duckdb \
  --game-id 2022090800 \
  --play-id 56 \
  --output data/exports/2022090800-56.json
```

Use **Open play JSON** in the app and select that export. The catalog loader
streams the week CSV and retains only the selected play, so memory use does not
scale with the full tracking file.

### 2026 pass-window release

The 2026 Big Data Bowl (`nfl-big-data-bowl-2026-analytics`) has a different shape: it covers
14,108 pass plays from the 2023 season, but each play only tracks what the competition's task
needed. `train/input_2023_wNN.csv` has every frame before the throw for the passer, route
runners, and coverage defenders (6–14 players, with speed, acceleration, direction, and
orientation). `train/output_2023_wNN.csv` has only x and y for the players to predict while the
pass is in the air. Game and play context, including formation and coverage, comes from
`supplementary_data.csv`. Place `supplementary_data.csv` and `train/` in one directory and ingest
it like any other release:

```bash
uv run football ingest bdb \
  --input data/raw/nfl-big-data-bowl-2026-analytics \
  --database data/db/bdb-2026.duckdb
```

The catalog joins the two windows into one replay, numbering the in-flight frames after the last
pre-throw frame. Post-throw speed, acceleration, and direction are served as unavailable (`null`),
not filled in. The source has no football, linemen, jersey numbers, or annotated events, so the
football-coverage and yard-line checks report `unavailable`. `pass_forward` (last pre-throw frame) and
`pass_arrived` (last in-flight frame) are derived from the windows and labeled as derived in the
quality report. There is no snap event, so snap-relative measurements and the protection envelope
are unavailable for these plays. Supplementary plays without tracking (3,901 of 18,009) are left
out and counted in the ingest warnings. On the development machine the full release ingests in
about 85 s with a 241 MB peak memory footprint, and 14,107 of 14,108 plays are graded valid. The
one incomplete play tracks only the passer in flight.

### Route atlas

Re-run the 2026 ingest command above once to upgrade existing catalogs to schema 6,
which indexes compact targeted-receiver paths alongside play metadata. Then run
`uv run football serve --database data/db/bdb-2026.duckdb` and `make dev`.
Open **Routes**, browse by route and man/zone coverage, and open a replay. Choose
**Find similar to current play**, then check **Overlay** on up to three results.
Comparison paths appear both in the atlas plot and on the replay field, translated
to the current receiver's release position. The **Routes** and **Landing** toggles
control the field overlays. The landing cross is the recorded pass destination,
not a tracked football position. Release and arrival boundaries are derived from
the source input/output windows.

Similarity is RMS Euclidean distance (yards) between 21 samples at equal fractions
of each observed pre-throw time window. Coordinates are normalized left-to-right
and centered on the target receiver at release. We preserve distance and lateral
direction: there is no scaling or lateral reflection. Duration is displayed but
does not affect ranking. This is geometric retrieval, not a trained model or a
claim that two plays share an assignment. Route labels apply only to the targeted
receiver; coverage describes the defense. Labels, landing points, and in-flight
positions are excluded from the similarity signature. There is no snap baseline.

`GET /routes` browses the index; adding `game_id` and `play_id` ranks other routes
against that play. Optional `route`, `coverage`, `coverage_type`, `page`, and `page_size` parameters
filter/paginate the results. Search returns metadata, compact paths, reference
geometry, filter options, and indexed/catalog counts. Invalid plays and paths with
missing/duplicate target frames, unknown direction, or ambiguous target identity
are excluded. Older sources without target-role labels report the atlas as
unavailable; existing 2026 catalogs request re-ingest rather than scanning CSVs
on each search. The local 2023 release yielded 14,108 indexed paths; a sample
full-catalog similarity query took about 44 ms on the development machine.

The official NFL GitHub sample uses an older game-level schema. Place its four
CSVs in `data/raw/nfl-official-2017-sample/`, then run `make sample`. The
catalog maps its legacy `frame.id`, `team`, player-name, and position fields,
infers play direction from the line of scrimmage when possible, and reports
acceleration and body orientation as unavailable rather than fabricating zeros.

## Local API

Start the read-only catalog API and web app in separate terminals:

```bash
make api
make dev
```

The API exposes `GET /health`, `GET /data-health`, filtered and paginated
`GET /plays` (including `epa_min`, `epa_max`, and `join_status` filters), and
`GET /plays/{game_id}/{play_id}`. The Vite development server proxies them under
`/api` to `127.0.0.1:8000`. Responses include source provenance and nflverse
join status without exposing absolute raw-data paths or serving source CSV files.

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
data/db            local DuckDB catalogs (gitignored)
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

The Python tests cover release validation, idempotent catalog ingestion,
filtered play search, catalog health, frame ordering, ball handling, player
metadata, and leftward-play rotation. The web tests cover derived spatial
metrics and event labels; typechecking and the production build catch the
integration surface.

## Next useful slices

1. Add duration-aware or fixed-time-window route comparison alongside the atlas's shape distance.
2. Aggregate route/coverage patterns with sample sizes, then evaluate trajectory prediction on held-out games.
3. Ingest nflverse participation data for formation and personnel in seasons that lack them.
4. Train only after establishing season/game splits that prevent play-family and team leakage.

## Pass-flight prediction lab

Pass-window plays support constant velocity, constant acceleration, and tuned damped acceleration for
the source-selected prediction participants. Choose **Ghost baseline** and turn on
**Ghosts** above the replay: hollow white markers
show projected positions, and dashed connectors show error against observed positions.
The prediction lab shares the replay playhead, supports release/arrival jumps and
keyboard scrubbing, and exposes per-player errors and missing-input states.

Generate the reproducible game-held-out benchmark and serve it with the catalog:

```bash
uv run football evaluate-flight --database data/db/bdb-2026.duckdb --output data/exports/pass-flight-damped.json
uv run football serve --database data/db/bdb-2026.duckdb --flight-report data/exports/pass-flight-damped.json
make dev
```

No re-ingest is needed for a current schema-6 catalog. Older JSON exports need to be
re-exported to include acceleration states. Damped ghosts additionally require the
matching report's tuned rate; missing/mismatched tuning stays unavailable.
Regenerate older reports: the comparison now uses `pass-flight-comparison-v3`.
Evaluation verifies source contents against
the catalog fingerprint; the API rejects reports from another catalog or baseline
version and verifies the tuning game IDs, rate, and source fingerprint. Without
`--flight-report`, the two untuned ghost baselines still work and the benchmark shows
an explicit unavailable state. The full report is available at `/flight-report`
(`/api/flight-report` through the development server).

On the local 2026 release (2023 season), the fixed split assigns 49 games to holdout
and 223 to development. **2,511 held-out plays / 8,261 player trajectories / 101,188
player-frames** are scored on identical observations for all three baselines:

- Constant velocity: **1.6414 yd coordinate RMSE, 1.4201 yd mean displacement error,
  2.7236 yd final displacement error**.
- Constant acceleration: **1.7609 yd coordinate RMSE, 1.1027 yd mean displacement
  error, 2.3124 yd final displacement error**.
- Damped acceleration: **1.2214 yd coordinate RMSE, 0.9131 yd mean displacement
  error, 1.8563 yd final displacement error**.

The damping rate is selected before held-out scoring, using only the 223
development games (11,597 plays / 461,748 player-frames). The fixed candidate grid
is **0, 0.25, 0.5, 1, 2, 4, 8 s⁻¹**, ranked by pooled development coordinate RMSE;
the smallest rate wins exact ties. The selected **λ = 2 s⁻¹** has an acceleration
half-life of **0.3466 s** and development RMSE **1.3818 yd**. These are tuning scores,
not validation scores. The report records every candidate's scores, exact tuning
game list, source fingerprint, and selected parameter; none are selected on held-out
labels. Tests change held-out outcomes and verify the selected rate is unchanged.

Damping improves held-out per-game RMSE in all 49 games versus velocity. It improves
overall RMSE by 0.4200 yd versus velocity and 0.5394 yd versus acceleration. It does
not win at every horizon: at 1.0 s its RMSE is 0.8868 yd versus acceleration's 0.8536;
at 2.0 s it scores 2.9863 versus acceleration's 4.3205 yd on the same 999 samples.

Acceleration improves mean and final error, but worsens aggregate RMSE by 0.1194 yd.
It improves per-game RMSE in 23 games and worsens it in 26. At 1.0 s, paired RMSE is
0.8536 yd versus velocity's 1.4717 yd (5,066 samples); at 2.0 s it is 4.3205 versus
3.8296 yd (999 samples). The unchanged velocity reference exactly reproduces the
original report. No holdout plays, release inputs, or labels were excluded/missing.
The JSON records all three baseline versions, exact game lists, source fingerprint, per-game,
per-role and per-horizon metrics, paired deltas, and exclusions. Its top-level
velocity scores preserve the original cohort; `comparison.baselines` uses the
intersection of available players for a fair comparison if history is missing.

The two undamped baselines are unfitted. Velocity is `v = (speed × sin(dir), speed × cos(dir))`
at the last input frame. Constant velocity uses `p(t) = p0 + v*t`. Constant acceleration
uses `p(t) = p0 + v*t + 0.5*a*t²`, with vector `a = (v_release - v_previous) / 0.1`.
The two input velocity observations must be unique and exactly 0.1 s apart; missing
history leaves acceleration unavailable and never falls back to velocity. This is
a backward difference in field coordinates, including turning and deceleration;
the source's scalar `a` and body orientation are unused. The
[official schema](https://www.kaggle.com/competitions/nfl-big-data-bowl-2026-analytics/data)
documents speed, scalar acceleration, and movement bearing as separate fields.
Acceleration is frozen without damping, speed caps, or a stopping rule; it can
reverse direction and overshoot on longer flights. Damped acceleration uses
`a(t) = a0 * exp(-λ*t)` and its exact position integral:
`p(t) = p0 + v*t + a0 * (λ*t + expm1(-λ*t)) / λ²`.
At λ = 0 this reduces to constant acceleration; a series expansion preserves
numerical accuracy near zero. Velocity itself is not damped. No parameters were
tuned on the holdout. The game split
uses the first eight hex digits of SHA-256 of `pass-flight-v1:<gameId>`, modulo 5;
bucket zero is held out. Neither landing point nor output positions nor flight
duration enter the predictor. Output length defines the evaluation window only.
Coordinate RMSE divides total squared Euclidean error by twice the observed
player-frame count. Mean displacement error is frame-weighted; final error uses
available labels at the play's last output frame. Missing labels are not interpolated,
and off-field forecasts are not clipped. Release/arrival boundaries are derived.
This fixed holdout has been inspected in previous baseline comparisons; it is a
repeated benchmark rather than a fresh blind test.

Dataset participant selection itself uses future throw information, so these scores
describe the selected receivers and defenders in this release, not all NFL players
or live-game performance. The 2017 sample lacks these prediction-participant labels
and remains unavailable for this lab. Learned models, landing-conditioned
forecasts, and uncertainty estimation are future work.
