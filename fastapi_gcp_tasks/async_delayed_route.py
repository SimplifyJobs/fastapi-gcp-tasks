# Standard Library Imports
from typing import Any, Unpack

# Third Party Imports
from fastapi.routing import APIRoute
from google.cloud import tasks_v2

# Imports from this repository
from fastapi_gcp_tasks._callback_url import resolve_callback_base_url
from fastapi_gcp_tasks.async_delayer import (
    AsyncCloudTasksClientFactory,
    AsyncCloudTasksClientProvider,
    AsyncDelayer,
)
from fastapi_gcp_tasks.hooks import DelayedTaskHook, noop_hook
from fastapi_gcp_tasks.protocols import AsyncDelayOptions, ensure_known_options


def AsyncDelayedRouteBuilder(  # noqa: N802
    *,
    queue_path: str,
    callback_base_url: str | None = None,
    base_url: str | None = None,
    task_create_timeout: float = 10.0,
    pre_create_hook: DelayedTaskHook | None = None,
    client: tasks_v2.CloudTasksAsyncClient | AsyncCloudTasksClientFactory | None = None,
    auto_create_queue: bool = False,
) -> type[APIRoute]:
    """
    Returns a Mixin that should be used to override route_class, with an awaitable .delay.

    It adds awaitable .delay and sync .options methods to the original endpoint.

    ``callback_base_url`` is the externally reachable URL prefix to which the
    route's own path is appended. It should include prefixes added by an outer
    ``include_router`` call. ``base_url`` is retained as a legacy alias.

    ``client`` may be a CloudTasksAsyncClient, a zero-argument factory returning one,
    or None (default client). grpc.aio channels bind to the event loop active at
    construction, so the client is resolved lazily on the first awaited ``.delay()``
    inside the running loop; pass a factory if your client needs custom construction
    (e.g. the emulator).

    Unlike DelayedRouteBuilder, ``auto_create_queue`` defaults to False so no
    unexpected RPCs run inside request handlers. Either pass
    ``auto_create_queue=True`` to lazily ensure the queue on the first
    ``.delay()``, or call ``fastapi_gcp_tasks.utils.ensure_queue_async`` from your
    FastAPI lifespan (recommended).

    Example:
    -------
    ```
      async_delayed_router = APIRouter(route_class=AsyncDelayedRouteBuilder(...), prefix="/delayed")

      class UserData(BaseModel):
          name: str

      @async_delayed_router.post("/on_user_create/{user_id}")
      @as_async_delayed_task  # optional: makes .delay visible to type checkers
      async def on_user_create(user_id: str, data: UserData):
          # do work here
          # Return values are meaningless

      # Await .delay to trigger
      await on_user_create.delay(user_id="007", data=UserData(name="Piyush"))

      app.include_router(async_delayed_router)
    ```

    """
    resolved_callback_base_url = resolve_callback_base_url(
        callback_base_url=callback_base_url,
        base_url=base_url,
    )
    hook: DelayedTaskHook = pre_create_hook if pre_create_hook is not None else noop_hook

    client_provider = AsyncCloudTasksClientProvider(client=client, auto_create_queue=auto_create_queue)

    class AsyncTaskRouteMixin(APIRoute):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            existing_delay = getattr(self.endpoint, "delay", None)
            # FastAPI <0.137 clones routes during inclusion. Keep the endpoint
            # bound to its original route so callback prefixing stays explicit.
            if isinstance(getattr(existing_delay, "__self__", None), AsyncTaskRouteMixin):
                return
            self.endpoint.options = self.delay_options  # type: ignore[attr-defined]
            self.endpoint.delay = self.delay  # type: ignore[attr-defined]

        def delay_options(self, **options: Unpack[AsyncDelayOptions]) -> AsyncDelayer:
            ensure_known_options(options, AsyncDelayOptions)
            opts: AsyncDelayOptions = {}
            endpoint_defaults = getattr(self.endpoint, "_delay_options", None)
            if endpoint_defaults:
                opts.update(endpoint_defaults)
            opts.update(options)

            # A per-call client override gets its own one-off provider
            provider = client_provider
            if "client" in opts:
                provider = AsyncCloudTasksClientProvider(
                    client=opts["client"],
                    auto_create_queue=auto_create_queue,
                )

            return AsyncDelayer(
                route=self,
                base_url=resolve_callback_base_url(
                    callback_base_url=opts.get("callback_base_url"),
                    base_url=opts.get("base_url"),
                    default=resolved_callback_base_url,
                ),
                queue_path=opts.get("queue_path", queue_path),
                task_create_timeout=opts.get("task_create_timeout", task_create_timeout),
                client_provider=provider,
                pre_create_hook=opts.get("pre_create_hook", hook),
                countdown=opts.get("countdown", 0),
                task_id=opts.get("task_id"),
            )

        async def delay(self, **kwargs: Any) -> tasks_v2.Task:
            return await self.delay_options().delay(**kwargs)

    return AsyncTaskRouteMixin
