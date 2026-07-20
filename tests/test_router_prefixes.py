"""Regression tests for callback URLs when task routers are included under an outer prefix."""

# Standard Library Imports
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

# Third Party Imports
from fastapi import APIRouter, FastAPI
from google.cloud import scheduler_v1, tasks_v2

# Imports from this repository
from fastapi_gcp_tasks import (
    AsyncDelayedRouteBuilder,
    AsyncScheduledRouteBuilder,
    DelayedRouteBuilder,
    ScheduledRouteBuilder,
    as_async_delayed_task,
    as_async_scheduled_task,
    as_delayed_task,
    as_scheduled_task,
)
from fastapi_gcp_tasks.async_scheduler import AsyncScheduler
from fastapi_gcp_tasks.scheduler import Scheduler

ORIGIN = "https://worker.example.com"
CALLBACK_BASE_URL = f"{ORIGIN}/tasks"
QUEUE_PATH = "projects/test-project/locations/us-central1/queues/test-queue"
LOCATION_PATH = "projects/test-project/locations/us-central1"


def test_delayed_route_uses_explicit_callback_base_for_outer_router_prefix() -> None:
    """A sync delayed task should target the same externally mounted path FastAPI serves."""
    client = MagicMock(spec=tasks_v2.CloudTasksClient)
    client.create_task.return_value = tasks_v2.Task()
    route_class = cast(Any, DelayedRouteBuilder)(
        callback_base_url=CALLBACK_BASE_URL,
        queue_path=QUEUE_PATH,
        client=client,
        auto_create_queue=False,
    )
    task_router = APIRouter(route_class=route_class, prefix="/auth")

    @task_router.post("/confirm/{user_id}")
    @as_delayed_task
    def confirm_user(user_id: str) -> None:
        """Confirm a user."""

    app = FastAPI()
    app.include_router(task_router, prefix="/tasks")

    confirm_user.delay(user_id="42")

    request = client.create_task.call_args.kwargs["request"]
    assert request.task.http_request.url == f"{ORIGIN}{app.url_path_for('confirm_user', user_id='42')}"


async def test_async_delayed_route_uses_explicit_callback_base_for_outer_router_prefix() -> None:
    """An async delayed task should target the same externally mounted path FastAPI serves."""
    client = MagicMock(spec=tasks_v2.CloudTasksAsyncClient)
    client.create_task = AsyncMock(return_value=tasks_v2.Task())
    route_class = cast(Any, AsyncDelayedRouteBuilder)(
        callback_base_url=CALLBACK_BASE_URL,
        queue_path=QUEUE_PATH,
        client=client,
    )
    task_router = APIRouter(route_class=route_class, prefix="/auth")

    @task_router.post("/confirm/{user_id}")
    @as_async_delayed_task
    async def confirm_user(user_id: str) -> None:
        """Confirm a user."""

    app = FastAPI()
    app.include_router(task_router, prefix="/tasks")

    await confirm_user.delay(user_id="42")

    request = client.create_task.await_args.kwargs["request"]
    assert request.task.http_request.url == f"{ORIGIN}{app.url_path_for('confirm_user', user_id='42')}"


def test_scheduled_route_uses_explicit_callback_base_for_outer_router_prefix() -> None:
    """A sync scheduled job should target the same externally mounted path FastAPI serves."""
    client = MagicMock(spec=scheduler_v1.CloudSchedulerClient)
    route_class = cast(Any, ScheduledRouteBuilder)(
        callback_base_url=CALLBACK_BASE_URL,
        location_path=LOCATION_PATH,
        client=client,
    )
    job_router = APIRouter(route_class=route_class, prefix="/maintenance")

    @job_router.post("/sweep")
    @as_scheduled_task
    def sweep() -> None:
        """Run periodic maintenance."""

    app = FastAPI()
    app.include_router(job_router, prefix="/tasks")

    scheduler = cast(Scheduler, sweep.scheduler(name="sweep", schedule="0 * * * *"))
    request = scheduler._build_create_job_request(values={})

    assert request.job.http_target.uri == f"{ORIGIN}{app.url_path_for('sweep')}"


def test_async_scheduled_route_uses_explicit_callback_base_for_outer_router_prefix() -> None:
    """An async scheduled job should target the same externally mounted path FastAPI serves."""
    client = MagicMock(spec=scheduler_v1.CloudSchedulerAsyncClient)
    route_class = cast(Any, AsyncScheduledRouteBuilder)(
        callback_base_url=CALLBACK_BASE_URL,
        location_path=LOCATION_PATH,
        client=client,
    )
    job_router = APIRouter(route_class=route_class, prefix="/maintenance")

    @job_router.post("/sweep")
    @as_async_scheduled_task
    async def sweep() -> None:
        """Run periodic maintenance."""

    app = FastAPI()
    app.include_router(job_router, prefix="/tasks")

    scheduler = cast(AsyncScheduler, sweep.scheduler(name="sweep", schedule="0 * * * *"))
    request = scheduler._build_create_job_request(values={})

    assert request.job.http_target.uri == f"{ORIGIN}{app.url_path_for('sweep')}"
