.PHONY: lint format test docs docs-build

lint:
	uv run scripts/lint.sh

format:
	uv run scripts/format.sh

test:
	uv run pytest -q -x -s

docs:
	uv run --group docs mkdocs serve

docs-build:
	uv run --group docs mkdocs build --strict
