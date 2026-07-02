"""Tests for the typed endpoint protocols, option TypedDicts, and task_default_options."""

# Standard Library Imports
from typing import cast
from unittest.mock import MagicMock

# Third Party Imports
import pytest
from fastapi import APIRouter, FastAPI
from google.cloud import scheduler_v1, tasks_v2
from pydantic import BaseModel

# Imports from this repository
import fastapi_gcp_tasks
from fastapi_gcp_tasks import (
    DelayedRouteBuilder,
    ScheduledRouteBuilder,
    as_delayed_task,
    as_scheduled_task,
    task_default_options,
)
from fastapi_gcp_tasks.delayer import Delayer

QUEUE_PATH = "projects/test-project/locations/us-central1/queues/test-queue"
LOCATION_PATH = "projects/test-project/locations/us-central1"
BASE_URL = "http://localhost"


class Item(BaseModel):
    """Simple model for testing."""

    name: str


def test_cast_helpers_are_identity() -> None:
    """The as_*_task helpers must return the function object unchanged."""

    def fn(item: Item) -> None:
        """Endpoint."""

    assert cast(object, as_delayed_task(fn)) is fn
    assert cast(object, as_scheduled_task(fn)) is fn


def test_task_default_options_stores_options() -> None:
    """task_default_options must attach its options for the route builder to read."""

    @task_default_options(countdown=10, task_id="abc")
    def fn() -> None:
        """Endpoint."""

    assert fn._delay_options == {"countdown": 10, "task_id": "abc"}  # type: ignore[attr-defined]


def test_public_api_exports() -> None:
    """Everything declared in __all__ must be importable."""
    for name in fastapi_gcp_tasks.__all__:
        assert getattr(fastapi_gcp_tasks, name) is not None


def test_delayed_route_typed_flow() -> None:
    """A typed endpoint should delay through the route's client with defaults and overrides applied."""
    client = MagicMock(spec=tasks_v2.CloudTasksClient)
    route_class = DelayedRouteBuilder(
        base_url=BASE_URL,
        queue_path=QUEUE_PATH,
        client=client,
    )
    app = FastAPI()
    router = APIRouter(route_class=route_class)

    @router.post("/task/{user_id}")
    @task_default_options(countdown=10)
    @as_delayed_task
    def my_task(user_id: str, item: Item) -> None:
        """Task endpoint."""

    app.include_router(router)

    # Endpoint defaults from task_default_options are applied
    delayer = cast(Delayer, my_task.options())
    assert delayer.countdown == 10

    # Per-call overrides win over endpoint defaults
    delayer = cast(Delayer, my_task.options(countdown=5, task_id="dedupe-key"))
    assert delayer.countdown == 5
    assert delayer.task_id == "dedupe-key"

    my_task.delay(user_id="42", item=Item(name="x"))
    request = client.create_task.call_args.kwargs["request"]
    assert request.task.http_request.url == f"{BASE_URL}/task/42"


def test_scheduled_route_typed_flow() -> None:
    """A typed scheduled endpoint should build a Scheduler with per-call overrides applied."""
    client = MagicMock(spec=scheduler_v1.CloudSchedulerClient)
    client.parse_common_location_path.side_effect = scheduler_v1.CloudSchedulerClient.parse_common_location_path
    route_class = ScheduledRouteBuilder(
        base_url=BASE_URL,
        location_path=LOCATION_PATH,
        client=client,
    )
    app = FastAPI()
    router = APIRouter(route_class=route_class)

    @router.post("/job")
    @as_scheduled_task
    def my_job(item: Item) -> None:
        """Job endpoint."""

    app.include_router(router)

    handle = my_job.scheduler(name="my-job", schedule="* * * * *", time_zone="Asia/Kolkata", force=True)
    # The handle protocol only promises schedule/delete; inspect the concrete Scheduler
    from fastapi_gcp_tasks.scheduler import Scheduler

    scheduler = cast(Scheduler, handle)
    assert isinstance(scheduler, Scheduler)
    assert scheduler.cron_schedule == "* * * * *"
    assert scheduler.time_zone == "Asia/Kolkata"
    assert scheduler.force is True
    assert scheduler.job_id.endswith("/jobs/my-job")


def test_unknown_options_raise_type_error() -> None:
    """Unknown option keys must fail fast at runtime instead of being silently dropped."""
    client = MagicMock(spec=tasks_v2.CloudTasksClient)
    route_class = DelayedRouteBuilder(
        base_url=BASE_URL,
        queue_path=QUEUE_PATH,
        client=client,
    )
    app = FastAPI()
    router = APIRouter(route_class=route_class)

    @router.post("/task")
    @as_delayed_task
    def my_task() -> None:
        """Task endpoint."""

    app.include_router(router)

    with pytest.raises(TypeError, match="countdwn"):
        my_task.options(countdwn=5)  # type: ignore[call-arg]

    with pytest.raises(TypeError, match="countdwn"):
        task_default_options(countdwn=5)  # type: ignore[call-arg]


def test_task_default_options_accepts_builder_overrides() -> None:
    """Builder-level defaults like base_url and client are valid decorator options at runtime."""

    @task_default_options(base_url="https://worker.example.com", countdown=10)
    def fn() -> None:
        """Endpoint."""

    assert fn._delay_options == {"base_url": "https://worker.example.com", "countdown": 10}  # type: ignore[attr-defined]


def test_job_changed_ignores_user_agent_on_both_sides() -> None:
    """User-Agent must be stripped from both jobs before comparing, without mutating the request."""
    from fastapi_gcp_tasks.scheduler import BaseScheduler

    def make_job(headers: dict[str, str]) -> scheduler_v1.Job:
        return scheduler_v1.Job(
            name="projects/p/locations/l/jobs/j",
            http_target=scheduler_v1.HttpTarget(uri="https://example.com", headers=headers),
            schedule="* * * * *",
        )

    # Hook sets a User-Agent on our request; GCP stamped one on the stored job.
    existing = make_job({"User-Agent": "Google-Cloud-Scheduler", "X-Custom": "1"})
    request = scheduler_v1.CreateJobRequest(
        parent="projects/p/locations/l",
        job=make_job({"User-Agent": "my-hook-agent", "X-Custom": "1"}),
    )

    assert BaseScheduler._job_changed(job=existing, request=request) is False
    # The request that will actually be sent must keep its headers.
    assert request.job.http_target.headers["User-Agent"] == "my-hook-agent"

    # A real difference is still detected.
    existing_diff = make_job({"X-Custom": "2"})
    assert BaseScheduler._job_changed(job=existing_diff, request=request) is True
