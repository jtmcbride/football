.PHONY: setup demo test web-build dev

setup:
	uv sync
	cd apps/web && npm install

demo:
	uv run football demo --output apps/web/public/plays/demo.json

test:
	uv run python -m unittest discover -s packages/ftbdata/tests -v
	cd apps/web && npm test -- --run
	cd apps/web && npm run typecheck

web-build:
	cd apps/web && npm run build

dev:
	cd apps/web && npm run dev
