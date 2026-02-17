.PHONY: lint format test

lint:
	uv run scripts/lint.sh

format:
	uv run scripts/format.sh

test:
	uv run pytest -q -x -s
