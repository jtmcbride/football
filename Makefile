.PHONY: setup demo sample test web-build api dev

setup:
	uv sync
	cd apps/web && npm install

demo:
	uv run football demo --output apps/web/public/plays/demo.json

sample:
	uv run football ingest bdb --input data/raw/nfl-official-2017-sample --database data/db/football.duckdb
	uv run football export --database data/db/football.duckdb --game-id 2017090700 --play-id 160 --output apps/web/public/plays/local-sample.json

test:
	uv run python -m unittest discover -s packages/ftbdata/tests -v
	cd apps/web && npm test -- --run
	cd apps/web && npm run typecheck

web-build:
	cd apps/web && npm run build

api:
	uv run football serve --database data/db/football.duckdb

dev:
	cd apps/web && npm run dev
