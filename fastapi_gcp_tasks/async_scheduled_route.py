# Standard Library Imports
from collections.abc import Callable, Coroutine
from typing import Any, Unpack

# Third Party Imports
from fastapi import Request, Response
from fastapi.routing import APIRoute
from google.cloud import scheduler_v1

# Imports from this repository
from fastapi_gcp_tasks.async_clients import AsyncClientProvider
from fastapi_gcp_tasks.async_scheduler import AsyncCloudSchedulerClientFactory, AsyncScheduler
from fastapi_gcp_tasks.hooks import ScheduledHook, noop_hook
from fastapi_gcp_tasks.protocols import AsyncSchedulerOptions


def AsyncScheduledRouteBuilder(  # noqa: N802
    *,
    base_url: str,
    location_path: str,
    job_create_timeout: float = 10.0,
    pre_create_hook: ScheduledHook | None = None,
    client: scheduler_v1.CloudSchedulerAsyncClient | AsyncCloudSchedulerClientFactory | None = None,
) -> type[APIRoute]:
    """
    Returns a Mixin that should be used to override route_class, with an awaitable scheduler.

    It adds a .scheduler method to the original endpoint whose .schedule and .delete
    coroutines must be awaited. Unlike ScheduledRouteBuilder, .schedule() cannot run at
    module import time — await it from a FastAPI lifespan or a request handler.

    ``client`` may be a CloudSchedulerAsyncClient, a zero-argument factory returning
    one, or None (default client). grpc.aio channels bind to the event loop active at
    construction, so the client is resolved lazily on the first awaited call; pass a
    factory if your client needs custom construction.

    Example:
    -------
    ```
    async_scheduled_router = APIRouter(route_class=AsyncScheduledRouteBuilder(...), prefix="/scheduled")

    @async_scheduled_router.get("/simple_scheduled_task")
    @as_async_scheduled_task  # optional: makes .scheduler visible to type checkers
    async def simple_scheduled_task():
        # Do work here

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await simple_scheduled_task.scheduler(name="simple_scheduled_task", schedule="* * * * *").schedule()
        yield

    app.include_router(async_scheduled_router)
    ```

    """
    hook: ScheduledHook = pre_create_hook if pre_create_hook is not None else noop_hook

    # One provider per builder so every scheduler reuses the same client and channel
    client_provider = AsyncClientProvider(client=client, client_cls=scheduler_v1.CloudSchedulerAsyncClient)

    class AsyncScheduledRouteMixin(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            original_route_handler = super().get_route_handler()
            self.endpoint.scheduler = self.scheduler_options  # type: ignore[attr-defined]
            return original_route_handler

        def scheduler_options(
            self, *, name: str, schedule: str, **options: Unpack[AsyncSchedulerOptions]
        ) -> AsyncScheduler:
            # A per-call client override gets its own one-off provider
            provider = client_provider
            if "client" in options:
                provider = AsyncClientProvider(
                    client=options["client"],
                    client_cls=scheduler_v1.CloudSchedulerAsyncClient,
                )

            return AsyncScheduler(
                route=self,
                base_url=options.get("base_url", base_url),
                location_path=options.get("location_path", location_path),
                schedule=schedule,
                client_provider=provider,
                pre_create_hook=options.get("pre_create_hook", hook),
                name=name,
                job_create_timeout=options.get("job_create_timeout", job_create_timeout),
                retry_config=options.get("retry_config"),
                time_zone=options.get("time_zone", "UTC"),
                force=options.get("force", False),
            )

    return AsyncScheduledRouteMixin
