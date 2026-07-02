"""Unit tests for AsyncScheduler using mocked async clients."""

# Standard Library Imports
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Third Party Imports
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from google.api_core.exceptions import NotFound
from google.cloud import scheduler_v1

# Imports from this repository
from fastapi_gcp_tasks.async_clients import AsyncClientProvider
from fastapi_gcp_tasks.async_scheduled_route import AsyncScheduledRouteBuilder
from fastapi_gcp_tasks.async_scheduler import AsyncScheduler
from fastapi_gcp_tasks.hooks import noop_hook
from fastapi_gcp_tasks.protocols import as_async_scheduled_task
from fastapi_gcp_tasks.scheduler import Scheduler

LOCATION_PATH = "projects/test-project/locations/us-central1"
BASE_URL = "http://localhost"


def _make_route() -> APIRoute:
    app = FastAPI()

    @app.post("/scheduled_hello")
    async def scheduled_hello() -> None:
        """Endpoint under test."""

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == "/scheduled_hello":
            return route
    raise ValueError("Route not found")


def _mock_async_client() -> MagicMock:
    client = MagicMock(spec=scheduler_v1.CloudSchedulerAsyncClient)
    client.get_job = AsyncMock(side_effect=NotFound("no job"))
    client.delete_job = AsyncMock(return_value=None)
    client.create_job = AsyncMock(return_value=scheduler_v1.Job())
    return client


def _make_scheduler(client: Any, **kwargs: Any) -> AsyncScheduler:
    provider = AsyncClientProvider(client=client, client_cls=scheduler_v1.CloudSchedulerAsyncClient)
    return AsyncScheduler(
        route=_make_route(),
        base_url=BASE_URL,
        location_path=LOCATION_PATH,
        schedule="*/5 * * * *",
        pre_create_hook=noop_hook,
        client_provider=provider,
        name="test-job",
        **kwargs,
    )


class TestAsyncScheduler:
    """Tests for AsyncScheduler schedule/delete flows."""

    async def test_schedule_creates_job_when_missing(self) -> None:
        """A missing job should be (re)created."""
        client = _mock_async_client()
        scheduler = _make_scheduler(client)

        await scheduler.schedule()

        client.create_job.assert_awaited_once()
        request = client.create_job.await_args.kwargs["request"]
        assert request.parent == LOCATION_PATH
        assert request.job.name == f"{LOCATION_PATH}/jobs/test-job"
        assert request.job.schedule == "*/5 * * * *"

    async def test_schedule_skips_unchanged_job(self) -> None:
        """An identical existing job should not be recreated."""
        client = _mock_async_client()
        scheduler = _make_scheduler(client)
        # Return the exact job we would create (plus a default User-Agent header)
        existing = scheduler._build_create_job_request(values={}).job
        existing.http_target.headers["User-Agent"] = "Google-Cloud-Scheduler"
        client.get_job = AsyncMock(return_value=scheduler_v1.Job(existing))

        await scheduler.schedule()

        client.delete_job.assert_not_awaited()
        client.create_job.assert_not_awaited()

    async def test_schedule_recreates_changed_job(self) -> None:
        """A differing existing job should be deleted and recreated."""
        client = _mock_async_client()
        scheduler = _make_scheduler(client)
        client.get_job = AsyncMock(return_value=scheduler_v1.Job(name=scheduler.job_id, schedule="0 0 * * *"))

        await scheduler.schedule()

        client.delete_job.assert_awaited_once()
        client.create_job.assert_awaited_once()

    async def test_schedule_force_recreates_without_diff(self) -> None:
        """force=True should skip the diff and always recreate."""
        client = _mock_async_client()
        scheduler = _make_scheduler(client, force=True)

        await scheduler.schedule()

        client.get_job.assert_not_awaited()
        client.delete_job.assert_awaited_once()
        client.create_job.assert_awaited_once()

    async def test_delete_returns_true_on_success(self) -> None:
        """delete() should return True when the RPC succeeds."""
        client = _mock_async_client()
        scheduler = _make_scheduler(client)

        assert await scheduler.delete() is True
        client.delete_job.assert_awaited_once_with(name=scheduler.job_id, timeout=scheduler.job_create_timeout)

    async def test_delete_returns_exception_on_failure(self) -> None:
        """delete() should return the exception when the RPC fails."""
        client = _mock_async_client()
        client.delete_job = AsyncMock(side_effect=NotFound("no job"))
        scheduler = _make_scheduler(client)

        result = await scheduler.delete()
        assert isinstance(result, NotFound)

    async def test_factory_resolved_lazily_once(self) -> None:
        """A client factory should only be called on first use, exactly once."""
        client = _mock_async_client()
        factory = MagicMock(return_value=client)
        scheduler = _make_scheduler(factory)
        factory.assert_not_called()

        await scheduler.schedule()
        await scheduler.delete()

        factory.assert_called_once()

    async def test_builder_shares_client_across_scheduler_calls(self) -> None:
        """All schedulers from one builder must reuse the same lazily-resolved client."""
        client = _mock_async_client()
        factory = MagicMock(return_value=client)
        route_class = AsyncScheduledRouteBuilder(
            base_url=BASE_URL,
            location_path=LOCATION_PATH,
            client=factory,
        )
        app = FastAPI()
        router = APIRouter(route_class=route_class)

        @router.post("/job")
        @as_async_scheduled_task
        async def my_job() -> None:
            """Job endpoint."""

        app.include_router(router)

        await my_job.scheduler(name="job-a", schedule="* * * * *").schedule()
        await my_job.scheduler(name="job-b", schedule="0 0 * * *").schedule()

        factory.assert_called_once()
        assert client.create_job.await_count == 2

    async def test_request_parity_with_sync_scheduler(self) -> None:
        """The async and sync schedulers should build identical CreateJobRequests."""
        async_scheduler = _make_scheduler(_mock_async_client())
        sync_scheduler = Scheduler(
            route=_make_route(),
            base_url=BASE_URL,
            location_path=LOCATION_PATH,
            schedule="*/5 * * * *",
            client=MagicMock(spec=scheduler_v1.CloudSchedulerClient),
            pre_create_hook=noop_hook,
            name="test-job",
        )

        assert async_scheduler._build_create_job_request(values={}) == sync_scheduler._build_create_job_request(
            values={}
        )
