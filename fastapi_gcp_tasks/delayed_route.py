# Standard Library Imports
from collections.abc import Callable, Coroutine
from typing import Any, Unpack

# Third Party Imports
from fastapi import Request, Response
from fastapi.routing import APIRoute
from google.cloud import tasks_v2

# Imports from this repository
from fastapi_gcp_tasks.delayer import Delayer
from fastapi_gcp_tasks.hooks import DelayedTaskHook, noop_hook
from fastapi_gcp_tasks.protocols import DelayOptions
from fastapi_gcp_tasks.utils import ensure_queue


def DelayedRouteBuilder(  # noqa: N802
    *,
    base_url: str,
    queue_path: str,
    task_create_timeout: float = 10.0,
    pre_create_hook: DelayedTaskHook | None = None,
    client: tasks_v2.CloudTasksClient | None = None,
    auto_create_queue: bool = True,
) -> type[APIRoute]:
    """
    Returns a Mixin that should be used to override route_class.

    It adds a .delay and .options methods to the original endpoint.

    Example:
    -------
    ```
      delayed_router = APIRouter(route_class=DelayedRouteBuilder(...), prefix="/delayed")

      class UserData(BaseModel):
          name: str

      @delayed_router.post("/on_user_create/{user_id}")
      @as_delayed_task  # optional: makes .delay visible to type checkers
      def on_user_create(user_id: str, data: UserData):
          # do work here
          # Return values are meaningless

      # Call .delay to trigger
      on_user_create.delay(user_id="007", data=UserData(name="Piyush"))

      app.include_router(delayed_router)
    ```

    """
    task_client = client if client is not None else tasks_v2.CloudTasksClient()
    hook: DelayedTaskHook = pre_create_hook if pre_create_hook is not None else noop_hook

    if auto_create_queue:
        ensure_queue(client=task_client, path=queue_path)

    class TaskRouteMixin(APIRoute):
        def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
            original_route_handler = super().get_route_handler()
            self.endpoint.options = self.delay_options  # type: ignore[attr-defined]
            self.endpoint.delay = self.delay  # type: ignore[attr-defined]
            return original_route_handler

        def delay_options(self, **options: Unpack[DelayOptions]) -> Delayer:
            opts: DelayOptions = {}
            endpoint_defaults = getattr(self.endpoint, "_delay_options", None)
            if endpoint_defaults:
                opts.update(endpoint_defaults)
            opts.update(options)

            return Delayer(
                route=self,
                base_url=opts.get("base_url", base_url),
                queue_path=opts.get("queue_path", queue_path),
                task_create_timeout=opts.get("task_create_timeout", task_create_timeout),
                client=opts.get("client", task_client),
                pre_create_hook=opts.get("pre_create_hook", hook),
                countdown=opts.get("countdown", 0),
                task_id=opts.get("task_id"),
            )

        def delay(self, **kwargs: Any) -> tasks_v2.Task:
            return self.delay_options().delay(**kwargs)

    return TaskRouteMixin
