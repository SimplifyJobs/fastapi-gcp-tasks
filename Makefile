.PHONY: lint format test

lint:
	uv run mypy fastapi_gcp_tasks
	uv run ruff check fastapi_gcp_tasks tests scripts examples
	uv run ruff format fastapi_gcp_tasks tests scripts examples --check

format:
	uv run ruff check fastapi_gcp_tasks tests examples scripts --fix
	uv run ruff format fastapi_gcp_tasks tests examples scripts

test:
	uv run pytest -q -x -s
