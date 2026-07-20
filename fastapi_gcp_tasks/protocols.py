# Standard Library Imports
from collections.abc import Callable, Mapping
from typing import ParamSpec, Protocol, TypedDict, TypeVar, Unpack, cast

# Third Party Imports
from google.cloud import scheduler_v1, tasks_v2

# Imports from this repository
from fastapi_gcp_tasks.hooks import DelayedTaskHook, ScheduledHook

P = ParamSpec("P")
R = TypeVar("R", covariant=True)


class TaskDefaultOptions(TypedDict, total=False):
    """
    Options accepted by the ``task_default_options`` decorator (shared by sync and async delayed routes).

    ``client`` is the only delay option not accepted here, because its type differs
    between the sync and async route builders.
    """

    countdown: int
    task_id: str
    task_create_timeout: float
    callback_base_url: str
    base_url: str
    queue_path: str
    pre_create_hook: DelayedTaskHook


class DelayOptions(TaskDefaultOptions, total=False):
    """Per-call overrides accepted by ``.options()`` on a delayed task endpoint."""

    client: tasks_v2.CloudTasksClient


class AsyncDelayOptions(TaskDefaultOptions, total=False):
    """Per-call overrides accepted by ``.options()`` on an async delayed task endpoint."""

    client: tasks_v2.CloudTasksAsyncClient | Callable[[], tasks_v2.CloudTasksAsyncClient]


class SchedulerOptions(TypedDict, total=False):
    """Per-call overrides accepted by ``.scheduler()`` on a scheduled task endpoint."""

    callback_base_url: str
    base_url: str
    location_path: str
    job_create_timeout: float
    retry_config: scheduler_v1.RetryConfig
    time_zone: str
    force: bool
    client: scheduler_v1.CloudSchedulerClient
    pre_create_hook: ScheduledHook


class AsyncSchedulerOptions(TypedDict, total=False):
    """Per-call overrides accepted by ``.scheduler()`` on an async scheduled task endpoint."""

    callback_base_url: str
    base_url: str
    location_path: str
    job_create_timeout: float
    retry_config: scheduler_v1.RetryConfig
    time_zone: str
    force: bool
    client: scheduler_v1.CloudSchedulerAsyncClient | Callable[[], scheduler_v1.CloudSchedulerAsyncClient]
    pre_create_hook: ScheduledHook


def ensure_known_options(options: Mapping[str, object], allowed: type) -> None:
    """
    Raise TypeError if ``options`` contains keys not declared on the ``allowed`` TypedDict.

    Type checkers already reject unknown keys statically; this keeps unchecked
    callers failing fast at runtime instead of silently dropping options.
    """
    unexpected = set(options) - (allowed.__required_keys__ | allowed.__optional_keys__)  # type: ignore[attr-defined]
    if unexpected:
        raise TypeError(f"Unknown option(s) for {allowed.__name__}: {', '.join(sorted(unexpected))}")


class DelayerHandle(Protocol[P]):
    """A configured delayer bound to an endpoint's signature."""

    def delay(self, *args: P.args, **kwargs: P.kwargs) -> tasks_v2.Task:
        """Create the task on Cloud Tasks. Call with keyword arguments matching the endpoint."""
        ...


class AsyncDelayerHandle(Protocol[P]):
    """A configured async delayer bound to an endpoint's signature."""

    async def delay(self, *args: P.args, **kwargs: P.kwargs) -> tasks_v2.Task:
        """Create the task on Cloud Tasks. Call with keyword arguments matching the endpoint."""
        ...


class SchedulerHandle(Protocol[P]):
    """A configured scheduler bound to an endpoint's signature."""

    def schedule(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """Create (or update) the job on Cloud Scheduler. Call with keyword arguments matching the endpoint."""
        ...

    def delete(self) -> bool | Exception:
        """Delete the job from Cloud Scheduler if it exists."""
        ...


class AsyncSchedulerHandle(Protocol[P]):
    """A configured async scheduler bound to an endpoint's signature."""

    async def schedule(self, *args: P.args, **kwargs: P.kwargs) -> None:
        """Create (or update) the job on Cloud Scheduler. Call with keyword arguments matching the endpoint."""
        ...

    async def delete(self) -> bool | Exception:
        """Delete the job from Cloud Scheduler if it exists."""
        ...


class DelayedTask(Protocol[P, R]):
    """
    Typed view of an endpoint registered on a DelayedRouteBuilder route.

    The ``.delay`` and ``.options`` attributes are attached at route registration
    time, so plain function annotations can't see them. Apply ``as_delayed_task``
    as the innermost decorator to give the endpoint this type.
    """

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Call the endpoint directly (as FastAPI does)."""
        ...

    def delay(self, *args: P.args, **kwargs: P.kwargs) -> tasks_v2.Task:
        """Trigger the task on Cloud Tasks. Call with keyword arguments matching the endpoint."""
        ...

    def options(self, **options: Unpack[DelayOptions]) -> DelayerHandle[P]:
        """Override task options for a single trigger, e.g. ``fn.options(countdown=5).delay(...)``."""
        ...


class AsyncDelayedTask(Protocol[P, R]):
    """
    Typed view of an endpoint registered on an AsyncDelayedRouteBuilder route.

    Apply ``as_async_delayed_task`` as the innermost decorator to give the
    endpoint this type.
    """

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Call the endpoint directly (as FastAPI does)."""
        ...

    async def delay(self, *args: P.args, **kwargs: P.kwargs) -> tasks_v2.Task:
        """Trigger the task on Cloud Tasks. Call with keyword arguments matching the endpoint."""
        ...

    def options(self, **options: Unpack[AsyncDelayOptions]) -> AsyncDelayerHandle[P]:
        """Override task options for a single trigger, e.g. ``await fn.options(countdown=5).delay(...)``."""
        ...


class ScheduledTask(Protocol[P, R]):
    """
    Typed view of an endpoint registered on a ScheduledRouteBuilder route.

    Apply ``as_scheduled_task`` as the innermost decorator to give the endpoint
    this type.
    """

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Call the endpoint directly (as FastAPI does)."""
        ...

    def scheduler(self, *, name: str, schedule: str, **options: Unpack[SchedulerOptions]) -> SchedulerHandle[P]:
        """Configure a Cloud Scheduler job for this endpoint; call ``.schedule(...)`` on the result."""
        ...


class AsyncScheduledTask(Protocol[P, R]):
    """
    Typed view of an endpoint registered on an AsyncScheduledRouteBuilder route.

    Apply ``as_async_scheduled_task`` as the innermost decorator to give the
    endpoint this type.
    """

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        """Call the endpoint directly (as FastAPI does)."""
        ...

    def scheduler(
        self, *, name: str, schedule: str, **options: Unpack[AsyncSchedulerOptions]
    ) -> AsyncSchedulerHandle[P]:
        """Configure a Cloud Scheduler job for this endpoint; await ``.schedule(...)`` on the result."""
        ...


def as_delayed_task(fn: Callable[P, R]) -> DelayedTask[P, R]:
    """
    Identity cast that types an endpoint as a DelayedTask.

    Apply as the innermost decorator (below the router decorator) so type
    checkers see ``.delay`` and ``.options`` with the endpoint's own signature:

    ```
    @delayed_router.post("/hello")
    @as_delayed_task
    def hello(p: Payload) -> None: ...


    hello.delay(p=Payload(...))  # statically checked
    ```
    """
    return cast(DelayedTask[P, R], fn)


def as_async_delayed_task(fn: Callable[P, R]) -> AsyncDelayedTask[P, R]:
    """Identity cast that types an endpoint as an AsyncDelayedTask. See ``as_delayed_task``."""
    return cast(AsyncDelayedTask[P, R], fn)


def as_scheduled_task(fn: Callable[P, R]) -> ScheduledTask[P, R]:
    """Identity cast that types an endpoint as a ScheduledTask. See ``as_delayed_task``."""
    return cast(ScheduledTask[P, R], fn)


def as_async_scheduled_task(fn: Callable[P, R]) -> AsyncScheduledTask[P, R]:
    """Identity cast that types an endpoint as an AsyncScheduledTask. See ``as_delayed_task``."""
    return cast(AsyncScheduledTask[P, R], fn)
