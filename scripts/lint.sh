#!/usr/bin/env bash

set -e
set -x

mypy fastapi_gcp_tasks
ruff check fastapi_gcp_tasks tests scripts examples
ruff format fastapi_gcp_tasks tests scripts examples --check