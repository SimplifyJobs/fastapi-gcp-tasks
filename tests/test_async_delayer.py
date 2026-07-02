"""Unit tests for AsyncDelayer and AsyncCloudTasksClientProvider using mocked async clients."""

# Standard Library Imports
import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Third Party Imports
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from google.api_core.exceptions import ServiceUnavailable
from google.cloud import tasks_v2
from pydantic import BaseModel

# Imports from this repository
from fastapi_gcp_tasks.async_delayed_route import AsyncDelayedRouteBuilder
from fastapi_gcp_tasks.async_delayer import AsyncCloudTasksClientProvider, AsyncDelayer
from fastapi_gcp_tasks.delayer import Delayer
from fastapi_gcp_tasks.hooks import noop_hook

QUEUE_PATH = "projects/test-project/locations/us-central1/queues/test-queue"
BASE_URL = "http://localhost"


class Item(BaseModel):
    """Simple model for testing."""

    name: str


def _make_route() -> APIRoute:
    app = FastAPI()

    @app.post("/hello/{user_id}")
    async def hello(user_id: str, item: Item) -> None:
        """Endpoint under test."""

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == "/hello/{user_id}":
            return route
    raise ValueError("Route not found")


def _mock_async_client() -> MagicMock:
    client = MagicMock(spec=tasks_v2.CloudTasksAsyncClient)
    client.create_task = AsyncMock(return_value=tasks_v2.Task())
    client.create_queue = AsyncMock(return_value=tasks_v2.Queue())
    client.parse_queue_path = tasks_v2.CloudTasksClient.parse_queue_path
    return client


def _make_delayer(client: Any, *, auto_create_queue: bool = False, **kwargs: Any) -> AsyncDelayer:
    provider = AsyncCloudTasksClientProvider(
        client=client,
        queue_path=QUEUE_PATH,
        auto_create_queue=auto_create_queue,
    )
    return AsyncDelayer(
        route=_make_route(),
        base_url=BASE_URL,
        queue_path=QUEUE_PATH,
        client_provider=provider,
        pre_create_hook=noop_hook,
        **kwargs,
    )


class TestAsyncDelayer:
    """Tests for AsyncDelayer.delay."""

    async def test_delay_creates_task(self) -> None:
        """delay() should await create_task with the built request."""
        client = _mock_async_client()
        delayer = _make_delayer(client)

        result = await delayer.delay(user_id="007", item=Item(name="bond"))

        assert isinstance(result, tasks_v2.Task)
        client.create_task.assert_awaited_once()
        request = client.create_task.await_args.kwargs["request"]
        assert request.parent == QUEUE_PATH
        assert request.task.http_request.url == f"{BASE_URL}/hello/007"
        assert b"bond" in request.task.http_request.body

    async def test_request_parity_with_sync_delayer(self) -> None:
        """The async and sync delayers should build identical CreateTaskRequests."""
        client = _mock_async_client()
        async_delayer = _make_delayer(client)
        sync_delayer = Delayer(
            route=_make_route(),
            base_url=BASE_URL,
            queue_path=QUEUE_PATH,
            client=MagicMock(spec=tasks_v2.CloudTasksClient),
            pre_create_hook=noop_hook,
        )
        values = {"user_id": "007", "item": Item(name="bond")}

        async_request = async_delayer._build_create_task_request(values=values)
        sync_request = sync_delayer._build_create_task_request(values=values)

        assert async_request == sync_request

    async def test_delay_with_task_id_sets_name(self) -> None:
        """A task_id should produce a deduplication name on the task."""
        client = _mock_async_client()
        delayer = _make_delayer(client, task_id="my-task")

        await delayer.delay(user_id="007", item=Item(name="bond"))

        request = client.create_task.await_args.kwargs["request"]
        assert request.task.name == f"{QUEUE_PATH}/tasks/my-task"

    async def test_delay_with_countdown_sets_schedule_time(self) -> None:
        """A countdown should set schedule_time on the task."""
        client = _mock_async_client()
        delayer = _make_delayer(client, countdown=60)

        await delayer.delay(user_id="007", item=Item(name="bond"))

        request = client.create_task.await_args.kwargs["request"]
        assert request.task.schedule_time is not None


class TestAsyncCloudTasksClientProvider:
    """Tests for lazy client resolution and queue auto-creation."""

    async def test_factory_resolved_exactly_once(self) -> None:
        """A client factory should be called once even across concurrent delays."""
        client = _mock_async_client()
        factory = MagicMock(return_value=client)
        provider = AsyncCloudTasksClientProvider(client=factory, queue_path=QUEUE_PATH)

        results = await asyncio.gather(*(provider.get() for _ in range(10)))

        factory.assert_called_once()
        assert all(r is client for r in results)

    async def test_client_instance_used_as_is(self) -> None:
        """A client instance should be returned unchanged."""
        client = _mock_async_client()
        provider = AsyncCloudTasksClientProvider(client=client, queue_path=QUEUE_PATH)

        assert await provider.get() is client

    async def test_no_auto_create_queue_by_default(self) -> None:
        """The default must never call create_queue."""
        client = _mock_async_client()
        delayer = _make_delayer(client)

        await delayer.delay(user_id="007", item=Item(name="bond"))

        client.create_queue.assert_not_awaited()

    async def test_auto_create_queue_ensures_once_across_concurrent_delays(self) -> None:
        """auto_create_queue=True should ensure the queue exactly once under concurrency."""
        client = _mock_async_client()
        delayer = _make_delayer(client, auto_create_queue=True)

        await asyncio.gather(*(delayer.delay(user_id=str(i), item=Item(name="x")) for i in range(10)))

        client.create_queue.assert_awaited_once()
        create_req = client.create_queue.await_args.kwargs["request"]
        assert create_req.queue.name == QUEUE_PATH

    async def test_failed_ensure_retries_without_recreating_client(self) -> None:
        """A failed queue ensure should be retried on the next delay, reusing the cached client."""
        client = _mock_async_client()
        client.create_queue = AsyncMock(side_effect=[ServiceUnavailable("emulator down"), tasks_v2.Queue()])
        factory = MagicMock(return_value=client)
        delayer = _make_delayer(factory, auto_create_queue=True)

        with pytest.raises(ServiceUnavailable):
            await delayer.delay(user_id="007", item=Item(name="bond"))

        result = await delayer.delay(user_id="007", item=Item(name="bond"))

        assert isinstance(result, tasks_v2.Task)
        factory.assert_called_once()
        assert client.create_queue.await_count == 2

    async def test_wrong_client_type_raises_clear_error(self) -> None:
        """A non-async, non-factory client should fail with a descriptive TypeError."""
        provider = AsyncCloudTasksClientProvider(client=object(), queue_path=QUEUE_PATH)  # type: ignore[arg-type]

        with pytest.raises(TypeError, match="CloudTasksAsyncClient"):
            await provider.get()

    async def test_factory_returning_wrong_type_raises_clear_error(self) -> None:
        """A factory that returns the wrong type should fail with a descriptive TypeError."""
        provider = AsyncCloudTasksClientProvider(client=lambda: None, queue_path=QUEUE_PATH)  # type: ignore[arg-type,return-value]

        with pytest.raises(TypeError, match="factory must return a CloudTasksAsyncClient"):
            await provider.get()


class TestAsyncDelayedRouteBuilder:
    """Tests for the route builder wiring."""

    async def test_endpoint_gets_awaitable_delay(self) -> None:
        """Endpoints on the async route should expose awaitable .delay and .options."""
        client = _mock_async_client()
        route_class = AsyncDelayedRouteBuilder(
            base_url=BASE_URL,
            queue_path=QUEUE_PATH,
            client=client,
        )
        app = FastAPI()
        router = APIRouter(route_class=route_class)

        @router.post("/task/{user_id}")
        async def my_task(user_id: str, item: Item) -> None:
            """Task endpoint."""

        app.include_router(router)

        result = await my_task.delay(user_id="42", item=Item(name="x"))  # type: ignore[attr-defined]
        assert isinstance(result, tasks_v2.Task)
        request = client.create_task.await_args.kwargs["request"]
        assert request.task.http_request.url == f"{BASE_URL}/task/42"

        # .options returns a fresh AsyncDelayer with overrides applied
        delayer = my_task.options(countdown=30)  # type: ignore[attr-defined]
        assert isinstance(delayer, AsyncDelayer)
        assert delayer.countdown == 30
