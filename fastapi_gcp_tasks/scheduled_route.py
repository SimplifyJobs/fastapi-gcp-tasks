# Standard Library Imports
from collections.abc import Callable, Coroutine
from typing import Any, Unpack

# Third Party Imports
from fastapi import Request, Response
from fastapi.routing import APIRoute
from google.cloud import scheduler_v1

# Imports from this repository
from fastapi_gcp_tasks.hooks import ScheduledHook, noop_hook
from fastapi_gcp_tasks.protocols import SchedulerOptions, ensure_known_options
from fastapi_gcp_tasks.scheduler import Scheduler


def ScheduledRouteBuilder(  # noqa: N802
    *,
    base_url: str,
    location_path: str,
    job_create_timeout: float = 10.0,
    pre_create_hook: ScheduledHook | None = None,
    client: scheduler_v1.CloudSchedulerClient | None = None,
) -> type[APIRoute]:
    """
    Returns a Mixin that should be used to override route_class.

    It adds a .scheduler method to the original endpoint.

    Example:
    -------
    ```
    scheduled_router = APIRouter(route_class=ScheduledRouteBuilder(...), prefix="/scheduled")

    @scheduled_router.get("/simple_scheduled_task")
    @as_scheduled_task  # optional: makes .scheduler visible to type checkers
    def simple_scheduled_task():
        # Do work here

    simple_scheduled_task.scheduler(name="simple_scheduled_task", schedule="* * * * *").schedule()

    app.include_router(scheduled_router)
    ```

    """
    scheduler_client = client if client is not None else scheduler_v1.CloudSchedulerClient()
    hook: ScheduledHook = pre_create_hook if pre_create_hook is not None else noop_hook

    class ScheduledRouteMixin(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            original_route_handler = super().get_route_handler()
            self.endpoint.scheduler = self.scheduler_options  # type: ignore[attr-defined]
            return original_route_handler

        def scheduler_options(self, *, name: str, schedule: str, **options: Unpack[SchedulerOptions]) -> Scheduler:
            ensure_known_options(options, SchedulerOptions)

            # An async client here would make create_job return a never-awaited
            # coroutine — fail fast instead.
            resolved_client = options.get("client", scheduler_client)
            if not isinstance(resolved_client, scheduler_v1.CloudSchedulerClient):
                raise TypeError(
                    f"ScheduledRouteBuilder requires a CloudSchedulerClient; got {type(resolved_client).__name__}. "
                    "Use AsyncScheduledRouteBuilder for CloudSchedulerAsyncClient."
                )

            return Scheduler(
                route=self,
                base_url=options.get("base_url", base_url),
                location_path=options.get("location_path", location_path),
                schedule=schedule,
                client=resolved_client,
                pre_create_hook=options.get("pre_create_hook", hook),
                name=name,
                job_create_timeout=options.get("job_create_timeout", job_create_timeout),
                retry_config=options.get("retry_config"),
                time_zone=options.get("time_zone", "UTC"),
                force=options.get("force", False),
            )

    return ScheduledRouteMixin
