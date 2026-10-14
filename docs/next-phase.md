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

## Objective

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
