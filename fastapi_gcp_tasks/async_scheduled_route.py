# Standard Library Imports
from typing import Any, Callable, Type

# Third Party Imports
from fastapi.routing import APIRoute
from google.cloud import scheduler_v1

# Imports from this repository
from fastapi_gcp_tasks.async_clients import AsyncClientProvider
from fastapi_gcp_tasks.async_scheduler import AsyncCloudSchedulerClientFactory, AsyncScheduler
from fastapi_gcp_tasks.hooks import ScheduledHook, noop_hook


def AsyncScheduledRouteBuilder(  # noqa: N802
    *,
    base_url: str,
    location_path: str,
    job_create_timeout: float = 10.0,
    pre_create_hook: ScheduledHook | None = None,
    client: scheduler_v1.CloudSchedulerAsyncClient | AsyncCloudSchedulerClientFactory | None = None,
) -> Type[APIRoute]:
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
    async def simple_scheduled_task():
        # Do work here

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await simple_scheduled_task.scheduler(name="simple_scheduled_task", schedule="* * * * *").schedule()
        yield

    app.include_router(async_scheduled_router)
    ```

    """
    if pre_create_hook is None:
        pre_create_hook = noop_hook

    # One provider per builder so every scheduler reuses the same client and channel
    client_provider = AsyncClientProvider(client=client, client_cls=scheduler_v1.CloudSchedulerAsyncClient)

    class AsyncScheduledRouteMixin(APIRoute):
        def get_route_handler(self) -> Callable:
            original_route_handler = super().get_route_handler()
            self.endpoint.scheduler = self.scheduler_options  # type: ignore[attr-defined]
            return original_route_handler

        def scheduler_options(self, *, name: str, schedule: str, **options: Any) -> AsyncScheduler:
            scheduler_opts = {
                "base_url": base_url,
                "location_path": location_path,
                "client_provider": client_provider,
                "pre_create_hook": pre_create_hook,
                "job_create_timeout": job_create_timeout,
                "name": name,
                "schedule": schedule,
            } | options

            # A per-call client override gets its own one-off provider
            if "client" in scheduler_opts:
                scheduler_opts["client_provider"] = AsyncClientProvider(
                    client=scheduler_opts.pop("client"),  # type: ignore[arg-type]
                    client_cls=scheduler_v1.CloudSchedulerAsyncClient,
                )

            # ignoring the type here because the dictionary values are unpacked
            return AsyncScheduler(route=self, **scheduler_opts)  # type: ignore[arg-type]

    return AsyncScheduledRouteMixin
