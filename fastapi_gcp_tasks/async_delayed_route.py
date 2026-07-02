# Standard Library Imports
from typing import Any, Callable, Type

# Third Party Imports
from fastapi.routing import APIRoute
from google.cloud import tasks_v2

# Imports from this repository
from fastapi_gcp_tasks.async_delayer import (
    AsyncCloudTasksClientFactory,
    AsyncCloudTasksClientProvider,
    AsyncDelayer,
)
from fastapi_gcp_tasks.hooks import DelayedTaskHook, noop_hook


def AsyncDelayedRouteBuilder(  # noqa: N802
    *,
    base_url: str,
    queue_path: str,
    task_create_timeout: float = 10.0,
    pre_create_hook: DelayedTaskHook | None = None,
    client: tasks_v2.CloudTasksAsyncClient | AsyncCloudTasksClientFactory | None = None,
    auto_create_queue: bool = False,
) -> Type[APIRoute]:
    """
    Returns a Mixin that should be used to override route_class, with an awaitable .delay.

    It adds awaitable .delay and sync .options methods to the original endpoint.

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
      async def on_user_create(user_id: str, data: UserData):
          # do work here
          # Return values are meaningless

      # Await .delay to trigger
      await on_user_create.delay(user_id="007", data=UserData(name="Piyush"))

      app.include_router(async_delayed_router)
    ```

    """
    if pre_create_hook is None:
        pre_create_hook = noop_hook

    client_provider = AsyncCloudTasksClientProvider(client=client, auto_create_queue=auto_create_queue)

    class AsyncTaskRouteMixin(APIRoute):
        def get_route_handler(self) -> Callable:
            original_route_handler = super().get_route_handler()
            self.endpoint.options = self.delay_options  # type: ignore[attr-defined]
            self.endpoint.delay = self.delay  # type: ignore[attr-defined]
            return original_route_handler

        def delay_options(self, **options: Any) -> AsyncDelayer:
            delay_opts = {
                "base_url": base_url,
                "queue_path": queue_path,
                "task_create_timeout": task_create_timeout,
                "client_provider": client_provider,
                "pre_create_hook": pre_create_hook,
            }
            if hasattr(self.endpoint, "_delay_options"):
                delay_opts |= self.endpoint._delay_options
            delay_opts |= options

            # A per-call client override gets its own one-off provider
            if "client" in delay_opts:
                delay_opts["client_provider"] = AsyncCloudTasksClientProvider(
                    client=delay_opts.pop("client"),  # type: ignore[arg-type]
                    auto_create_queue=auto_create_queue,
                )

            # ignoring the type here because the dictionary values are unpacked
            return AsyncDelayer(
                route=self,
                **delay_opts,  # type: ignore[arg-type]
            )

        async def delay(self, **kwargs: Any) -> tasks_v2.Task:
            return await self.delay_options().delay(**kwargs)

    return AsyncTaskRouteMixin
