#!/bin/sh -e
set -x

ruff check fastapi_gcp_tasks tests examples scripts --fix
ruff format fastapi_gcp_tasks tests examples scripts