# Configuration

## DelayedRouteBuilder

```python
DelayedRoute = DelayedRouteBuilder(...)
delayed_router = APIRouter(route_class=DelayedRoute)


@delayed_router.get("/simple_task")
def simple_task() -> None: ...
```

| Option | Description |
| --- | --- |
| `base_url` | The URL of your worker FastAPI service. |
| `queue_path` | Full path of the Cloud Tasks queue. (Hint: use the [`queue_path`](../api/utils.md) util.) |
| `task_create_timeout` | How long to wait before giving up on creating the cloud task. Default `10.0` seconds. |
| `pre_create_hook` | Edit the `CreateTaskRequest` before it is sent (e.g. auth for Cloud Run). See [Hooks](hooks-and-dependencies.md). |
| `client` | Override the `CloudTasksClient` (e.g. custom credentials or transport, the emulator). |
| `auto_create_queue` | Ensure the queue exists at builder creation time. Default `True`. |

### Task-level default options

All `Delayer` options can be set per-endpoint with the `task_default_options` decorator:

```python
from fastapi_gcp_tasks import task_default_options


# Trigger after 5 minutes
@delayed_router.get("/simple_task")
@task_default_options(countdown=300)
def simple_task() -> None: ...
```

Additional options beyond the builder options:

| Option | Description |
| --- | --- |
| `countdown` | Seconds in the future to schedule the task. |
| `task_id` | Named task id for deduplication. (One task id will only be queued once.) |

### Per-call options

Everything above can be overridden per call (including builder options like `base_url`) with `.options()`
before calling `.delay()`:

```python
# Trigger after 2 minutes
simple_task.options(countdown=120).delay()
```

The accepted keys are typed as the [`DelayOptions` TypedDict](../api/protocols.md).

## AsyncDelayedRouteBuilder

Same options as `DelayedRouteBuilder`, with two differences:

| Option | Description |
| --- | --- |
| `client` | A `CloudTasksAsyncClient`, a zero-argument factory returning one, or `None`. Resolved lazily on the first awaited `.delay()` because grpc.aio clients bind to the running event loop. |
| `auto_create_queue` | Defaults to `False` (the sync builder defaults to `True`). When `True`, the queue is ensured lazily on the first `.delay()`. Prefer calling `ensure_queue_async` from your lifespan instead. |

## ScheduledRouteBuilder

```python
ScheduledRoute = ScheduledRouteBuilder(...)
scheduled_router = APIRouter(route_class=ScheduledRoute)


@scheduled_router.get("/simple_scheduled_task")
def simple_scheduled_task() -> None: ...


simple_scheduled_task.scheduler(name="simple_scheduled_task", schedule="* * * * *").schedule()
```

| Option | Description |
| --- | --- |
| `base_url` | The URL of your worker FastAPI service. |
| `location_path` | Full location path for Cloud Scheduler. (Hint: use the [`location_path`](../api/utils.md) util.) |
| `job_create_timeout` | How long to wait before giving up on creating the job. Default `10.0` seconds. |
| `pre_create_hook` | Edit the `CreateJobRequest` before it is sent. See [Hooks](hooks-and-dependencies.md). |
| `client` | Override the `CloudSchedulerClient`. |

`.scheduler(...)` accepts `name` and `schedule` (cron expression) as required keywords, plus per-call
overrides typed as the [`SchedulerOptions` TypedDict](../api/protocols.md): `time_zone` (default `"UTC"`),
`retry_config`, `force`, and the builder options above.

## AsyncScheduledRouteBuilder

Same options as `ScheduledRouteBuilder`, except `client` accepts a `CloudSchedulerAsyncClient`, a
zero-argument factory returning one, or `None` (resolved lazily, as above). `.schedule()` and `.delete()`
are coroutines — await them from a lifespan or a request handler.
