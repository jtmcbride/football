# Next Phase: Real-Data Catalog and Play Explorer

## Implementation status

Milestone 1 now includes release schema validation, content fingerprinting,
DuckDB metadata indexing, idempotent ingest, filtered play search, catalog
health, normalized play loading, CLI commands, and controlled-fixture tests.
The catalog has also been validated end to end against the NFL's official 2017
sample: 177 plays were indexed and a 74-frame, 23-entity play was rendered in
the web viewer. A legacy adapter maps game-level tracking files and reports
fields absent from that release. The local API foundation is now implemented
with health, sanitized data-health, filtered play search, and normalized play
endpoints plus contract tests. The searchable play browser is implemented, with
shareable game/play/frame URLs, working browser history, and filters for offense,
defense, play type, description, season, week, down, EPA range, and nflverse join
status (season and week options come from the catalog; EPA and nflverse filters
are disabled with an explanation when no play-by-play data is loaded). nflverse enrichment
(Milestone 3) is implemented: season play-by-play Parquet files are ingested into
separate DuckDB tables, joined to tracking plays by game, play, and season, and
reported as `matched`, `conflicting`, `unmatched`, or `unavailable` with measured
coverage by season and week. All 177 plays of the official 2017 sample match the
2017 nflverse file. Milestone 2 is implemented: every play is assessed by twelve
named checks (source rows, field bounds, frame order, 10 Hz cadence, player identity,
football coverage, event order, entity count, play direction, yard-line cross-check,
heading versus motion, source fields) and graded `valid`, `incomplete`, `invalid`,
or `generated`. Ingest streams every tracking file once and stores the result in a
`play_quality` table, so the ingest report, `football quality`, `GET /data-health`,
the play search (`quality_status`), and the sidebar all report the same measured
coverage; each served play carries a compact `provenance` block. The full 2025 release is no
longer downloadable, so the catalog was profiled on the 2026 analytics release instead. That release is
a pass-window format: 14,108 tracked pass plays from 272 games in the 2023 season. Each play has
pre-throw frames for the passer, route runners, and coverage defenders, then x/y for the players to
predict while the ball is in the air. It has no football, linemen, or events, and a supplementary file
provides context. A `pass_window` adapter catalogs it behind the same `TrackingCatalog` interface. Full
ingest takes about 85 s with a 241 MB peak memory footprint, so resumable fingerprint checkpoints are
not needed yet. 14,107 plays are valid; the one incomplete play tracks only the passer. Heading versus
motion passes on 14,087 plays, the first large-scale confirmation that x, y, and `dir` rotate together,
and acceleration and orientation are now present in real data. The release gate is still only
partially met: no full 22-player release is available to verify the ball, yard-line, protection, and
event checks at scale. Remaining work is filters for
formation, personnel, and result (blocked on nflverse participation data for seasons
that lack them), and persisting filters in the URL. The thresholds were validated
against the NFL's official 2017 single-game sample: 169 of 177 plays are valid, eight
are incomplete, and none are invalid. The remaining warnings are five short coordinate
dropouts, one 21-player play, one play whose direction cannot be inferred at midfield,
and one event-alignment inconsistency. This is still only one game. The legacy source
has no acceleration or orientation, and its yard-line cross-check is unavailable
because direction and the line of scrimmage are inferred from the same ball positions.

## Pass-flight prediction follow-on

Constant-velocity, constant-acceleration, and damped-acceleration baselines are implemented on top of the
route atlas and the 2026 pass-window adapter. Release position, speed and movement
direction define velocity; acceleration is a backward difference of the final two
input velocity vectors, exactly 0.1 s apart. The source scalar acceleration is unused.
Missing prior velocity makes acceleration unavailable. Future labels are accessed
only for scoring. The replay offers a baseline selector and shows hollow
ghosts, error connectors, per-player displacement errors and linked flight scrubbing.
Missing motion inputs/labels remain unavailable and projections are never clipped.

`football evaluate-flight` verifies source bytes against the catalog, uses a fixed
SHA-256 game split (bucket zero of five), and writes a versioned JSON report with
exact game lists, fingerprint, exclusions, and metrics by game, role and 0.1-second
horizon. The two undamped baselines have no fitted parameters. In the current 2023-season release, 49 held-out
games produce 2,511 plays, 8,261 trajectories and 101,188 observed player-frames:
coordinate RMSE 1.6414 yd, mean Euclidean error 1.4201 yd, final error 2.7236 yd.
All holdout inputs and labels were available; 223 games remain in development.
Targeted-receiver RMSE is 1.3276 yd; coverage-defender RMSE is 1.7494 yd.
At 1.0 s RMSE is 1.4717 yd (5,066 samples); at 2.0 s it is 3.8296 yd (999 samples).
Changing horizon also changes the cohort, so these are not fixed-cohort growth curves.

The paired acceleration comparison uses the same 49 held-out games and all 101,188
observations, with no missing history in this run. Acceleration scores 1.7609 yd
coordinate RMSE, 1.1027 yd mean error, and 2.3124 yd final error. Its RMSE difference
from velocity is +0.1194 yd, despite improved mean and final error. It improves
per-game RMSE in 23 games and worsens it in 26. At 1.0 s acceleration RMSE is 0.8536 yd
(5,066 paired samples); at 2.0 s it is 4.3205 yd (999 paired samples). The unbounded
quadratic extrapolation can overshoot on longer horizons; no damping/caps were tuned
on the holdout. The UI shows all curves on a shared scale, with paired deltas,
role summaries, and sample counts. Report version `pass-flight-comparison-v3`
preserves the original velocity cohort at the top level and records paired metrics
under `comparison`; regenerate older reports before serving. The full
velocity reference, source fingerprint and game lists exactly match the previous run.

Damped acceleration adds exponential decay `a(t)=a0*exp(-λ*t)` and its exact position
integral. λ is selected from the fixed grid 0, 0.25, 0.5, 1, 2, 4, 8 s⁻¹, minimizing
pooled coordinate RMSE on development games only; smallest λ breaks exact ties.
All 223 development games yield 11,597 scored plays / 461,748 player-frames. λ = 2 s⁻¹
wins with development RMSE 1.3818 yd and acceleration half-life 0.3466 s. These are
in-sample tuning scores. Selection finishes before held-out scoring begins.
The report's `tuning` block records all candidates, game IDs, source fingerprint,
and the selected parameter. An outcome-mutation test verifies that changing held-out
labels cannot change the selected rate. The API rejects mismatched tuning artifacts;
damped ghosts require a matching report and have no hardcoded rate fallback.

On the same 49 held-out games / 101,188 matched player-frames, damping scores
1.2214 yd RMSE, 0.9131 yd mean error, and 1.8563 yd final error. It improves per-game
RMSE versus velocity in all 49 games. At 1.0 s its RMSE is 0.8868 yd (5,066 samples);
at 2.0 s it is 2.9863 yd (999 samples). The two prior baselines and exact split lists
reproduce unchanged. This is a repeated benchmark whose prior results were inspected,
not a fresh blind evaluation. No held-out labels were used to select λ.

Remaining prediction work: compare additional baselines using development games,
introduce a separate validation split for more extensive tuning, and retain the game holdout
for final comparisons. Any landing-conditioned model must be labeled separately.
Source participants are selected using eventual throw information, release/arrival
events are derived, and frame-weighted metrics give longer flights more weight.
Neither this single-season benchmark nor the 2017 single-game sample establishes
league-wide or live-game accuracy. The initial phase's predictive-model non-goal
below remains historical; this separately scoped follow-on introduces these baselines.

## Route atlas follow-on

The first route-atlas slice is implemented for pass-window releases. Served plays
expose target roles, targeted-receiver route, coverage, formation, normalized
landing coordinates, and derived release/arrival frame boundaries. Catalog schema
6 stores 21-point release-relative pre-throw path signatures during ingestion.
The read-only `/routes` endpoint supports browsing, route/man-zone filtering, and
geometric nearest-route search. The UI supports opening results and overlaying up
to three comparisons on a release-relative plot and the replay field. Search is
independent of route/coverage labels and future landing/in-flight coordinates;
duration is displayed separately and time is normalized within each observation
window. Missing target frames are excluded rather than bridged. All 14,108 local
2023 pass-window plays yielded pre-throw target paths, including the play with
incomplete in-flight coverage. The legacy 2017 sample has no target-role labels
and remains unavailable for this atlas.

Next: compare fixed-duration windows, aggregate route/coverage cohorts with sample
sizes, and establish held-out-game baselines before introducing learned trajectory
models. The atlas's geometric ranking is descriptive and does not infer assignments.

## Original phase objective

Move Football Motion Lab from opening one exported JSON file at a time to a
local, searchable library of real NFL Big Data Bowl plays enriched with
nflverse play-by-play context.

At the end of this phase, a user should be able to:

1. Place an accepted Big Data Bowl download in `data/raw/`.
2. Run one ingestion command.
3. Start the local API and web application.
4. Find a play by season, week, team, situation, or result.
5. Replay and inspect that play with validated tracking and nflverse context.

## Architectural direction

The central addition will be a deep `TrackingCatalog` module. Its interface
should stay small while its implementation owns the complicated work:

```python
catalog.ingest_release(source_directory) -> IngestReport
catalog.find_plays(filters, page) -> PlayPage
catalog.load_play(game_id, play_id) -> TrackingPlay
catalog.data_health() -> DataHealth
```

The module will hide:

- Big Data Bowl schema validation and schema-version differences
- CSV scanning and DuckDB indexing
- player and football row handling
- coordinate, orientation, and line-of-scrimmage normalization
- event canonicalization
- nflverse joins
- provenance and coverage reporting
- conversion to the existing `TrackingPlay` interchange format

The existing `TrackingPlay` format remains the seam between the data layer and
the visualization. This prevents storage and ingestion changes from spreading
through the replay components.

Two adapters will sit at that seam:

- the current static schematic-play adapter for zero-setup use and tests
- the new DuckDB-backed catalog adapter for real tracking data

## Milestone 1: Catalog and ingestion foundation

Add a DuckDB catalog that indexes a downloaded Big Data Bowl release without
copying or redistributing its raw files.

### Work

- Add `football ingest bdb --input data/raw/<release>`.
- Discover and validate `games.csv`, `plays.csv`, `players.csv`,
  `player_play.csv`, and `tracking_week_*.csv`.
- Record games, plays, players, tracking-file locations, and source metadata in
  DuckDB.
- Preserve the existing streaming single-play extraction path.
- Generate a deterministic release fingerprint from source filenames, sizes,
  and hashes.
- Return an `IngestReport` with row counts, warnings, errors, and coverage.
- Make repeated ingestion idempotent and resumable.

### Acceptance criteria

- A valid release produces a searchable catalog with deterministic counts.
- Re-running ingestion does not duplicate records.
- A missing or incompatible source file fails with an actionable message.
- A cataloged play loads into the current viewer without changing the viewer's
  data contract.

## Milestone 2: Data quality and provenance

Make data correctness visible and fail closed when tracking cannot support a
requested analysis.

### Quality checks

- coordinates remain finite and off-field excursions stay within a plausible tracking perimeter
- frames are ordered and frame identifiers are unique within a play
- timing is consistent with the expected 10 Hz tracking cadence
- player identities are stable across frames
- football coverage is measured and missing-ball intervals are reported
- event frames are ordered consistently
- normalized plays always move left-to-right
- `x`, `y`, `dir`, `o`, and the absolute yard line rotate together
- entity-count anomalies are reported rather than silently discarded

### Provenance fields

- source release and competition year
- input filenames and release fingerprint
- ingestion time and software version
- original and normalized play direction
- available and missing source fields
- nflverse join status
- validation warnings and errors

### Acceptance criteria

- Every served play includes a compact provenance summary.
- The UI distinguishes valid, incomplete, generated, and unjoined data.
- The ingestion command emits a machine-readable quality report.

### Implemented grading

- A check is `pass`, `info`, `unavailable`, `warning`, or `error`. A play is `invalid`
  if any check errors, `incomplete` if any warns, otherwise `valid`; demo plays are
  always `generated`. `info` and `unavailable` never downgrade a play, so a source
  that simply lacks a field (the legacy 2017 sample has no `a` or `o`) is disclosed
  in `provenance.fields.missing` rather than marked incomplete.
- "Unjoined" is the nflverse join state (`unmatched` or `unavailable`), shown as its
  own badge beside the tracking-quality badge.
- Elapsed time follows frame ids (`timeMs = (frameId - firstFrameId) * 100`), so a
  missing frame appears as a gap in the timeline instead of being closed up.
- Rows that cannot be parsed are skipped and counted as a `warning` finding instead of
  aborting extraction; duplicate player rows remain an `error` because they are ambiguous.
- Entity-major source rows are checked within each entity's timeline, and source
  timestamps are used for cadence only when their disclosed precision can resolve 100 ms.
- The official 2017 sample records legitimate boundary movement up to 16.1 yd outside
  the painted field. Excursions up to 20 yd are disclosed as `info`; larger values warn,
  and values beyond 50 yd error.
- The yard-line cross-check cannot detect a flipped play near midfield and is
  `unavailable` when direction was inferred from the ball (legacy releases).

## Milestone 3: nflverse enrichment

Join tracking data to public nflverse play-by-play while preserving the original
source fields and reporting unmatched records.

### Work

- Ingest the relevant nflverse play-by-play Parquet files by season.
- Join Big Data Bowl `gameId` to nflverse `old_game_id` and Big Data Bowl
  `playId` to nflverse `play_id`.
- Add EPA, WPA, play result, clock, score, down and distance, formation,
  personnel, air yards, yards after catch, and penalty context where available.
- Store join status and field-level availability.
- Produce release-, season-, and week-level join coverage reports.

### Acceptance criteria

- Join coverage is measured and displayed, not inferred.
- Unmatched tracking plays remain accessible with their original context.
- No play is silently removed because enrichment is unavailable.

## Milestone 4: Local API

Add a small FastAPI application similar in shape to the baseball project.

### Initial interface

- `GET /health` — process and catalog readiness
- `GET /data-health` — source, validation, and join coverage
- `GET /plays` — paginated play search and filters
- `GET /plays/{game_id}/{play_id}` — normalized `TrackingPlay`
- `GET /games/{game_id}` — game metadata and available plays

### Search filters

- season and week
- offense and defense
- down and yards to go
- pass, rush, sack, penalty, or other play type
- formation and personnel
- EPA range and result
- source-validation status

### Acceptance criteria

- API contract tests cover successful, missing, incomplete, and invalid plays.
- Historical results are cacheable and deterministic.
- The API never exposes raw source files.

## Milestone 5: Play browser

Replace manual JSON selection as the primary workflow while retaining it as a
useful development and import path.

### Work

- Add a searchable game and play sidebar.
- Show compact situation, result, and data-health summaries for each play.
- Add season, week, team, play-type, and situation filters.
- Preserve the selected play and frame in the URL.
- Provide loading, empty, partial-data, and API-unavailable states.
- Keep the schematic demo available when no local catalog exists.

### Acceptance criteria

- A user can locate and open a real play without knowing its identifiers.
- Browser navigation and copied URLs restore the same play and frame.
- The layout remains usable on desktop and narrow screens.

## Milestone 6: First analytical views

Add descriptive spatial analysis before attempting predictive modeling.

Milestone 6 is implemented in two descriptive slices. In 6A, speed and nearest-opponent
time series share the replay playhead; route depth, signed lateral movement, and
straight-line displacement are measured from the snap; nearest-opponent identity
is reported per frame; and snap, release, arrival, catch, and tackle markers are
aligned to the chart when those events exist. The disclosed analysis window runs
from the snap through the first tackle, or the final tracked frame when no tackle
is present. Missing observations remain visible gaps, and unavailable acceleration
is never zero-filled. Controlled geometry tests cover known distances, missing
frames, absent snap baselines, and both tackle-ended and final-frame windows.
6B adds offense and defense centroids, RMS spatial spread, centroid separation,
quarterback depth from his normalized snap point, and a field overlay for the
protection envelope. The envelope is explicitly a convex hull of the quarterback
and tracked offensive linemen, not an inference about assignments, pressure, or
protection quality. Team-count gaps disclose that only tracked players contribute.
Controlled fixtures verify centroids, spread, depth, hull dimensions, and area.
Acceleration remains unavailable in the 2017 source and is disclosed rather than
zero-filled; its profile still needs validation on a source that provides the field.

### Measurements

- receiver-defender separation over time
- route depth, width, and displacement
- offensive and defensive centroids and spatial spread
- player speed and acceleration profiles
- quarterback depth and pocket shape
- event-aligned values at snap, pass release, arrival, catch, and tackle

### Presentation

- a selected-player time-series panel
- a separation-over-time chart linked to the replay frame
- route trails with event markers
- metric definitions and source-availability notes
- explicit unavailable states instead of zero-filled measurements

### Acceptance criteria

- Scrubbing either a chart or the replay updates the other.
- Measurements are tested with controlled fixtures and known geometry.
- Metrics disclose the event window and entities used in their calculation.

## Verification strategy

### Unit tests

- schema parsing and field coercion
- coordinate and angle normalization
- catalog queries and pagination
- spatial measurements on controlled fixtures
- provenance and availability rules

### Integration tests

- ingest a minimal fixture release into a temporary DuckDB database
- query and load a play through the catalog interface
- exercise API filtering and error contracts
- verify nflverse join coverage and unmatched-play preservation

### Browser tests

- search and select a real fixture play
- play, pause, scrub, and jump to events
- restore play and frame from a URL
- verify partial-data and unavailable-API states

### Release gate

Before considering the phase complete:

- all Python and web tests pass
- TypeScript typechecking and the production build pass
- `git diff --check` passes
- a real user-supplied Big Data Bowl release is ingested successfully
- at least one real play is verified end to end in the browser
- source provenance and nflverse join coverage are visible in the UI

## Delivery order

Implement the milestones in this dependency order:

1. Catalog interface, DuckDB implementation, and ingestion report
2. Validation and provenance
3. nflverse enrichment
4. FastAPI application
5. Play browser
6. Linked analytical views

Each milestone should leave the application runnable and should be committed as
a focused, reviewable feature.

## Explicit non-goals

The following should remain outside this phase:

- predictive or player-ranking models
- claims of league-wide generalization
- public redistribution of Big Data Bowl source files
- hosted multi-user deployment
- live-game ingestion
- support for every historical Big Data Bowl schema before the selected release
  works end to end

Predictive modeling should begin only after the catalog, provenance, coverage,
and season/game split semantics are dependable.
