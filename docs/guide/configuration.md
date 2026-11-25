---
description: >-
  Every option for DelayedRouteBuilder, ScheduledRouteBuilder and their async variants:
  callback URLs, queues, timeouts, hooks, clients, and per-task overrides.
---

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
| `callback_base_url` | The externally reachable URL prefix to which the task route's own path is appended. Include any prefix added later by an outer `include_router()` call — see [below](#routers-mounted-under-an-outer-prefix). |
| `base_url` | Legacy alias for `callback_base_url`. Pass only one of the two. |
| `queue_path` | Full path of the Cloud Tasks queue. (Hint: use the [`queue_path`](../api/utils.md) util.) |
| `task_create_timeout` | How long to wait before giving up on creating the cloud task. Default `10.0` seconds. |
| `pre_create_hook` | Edit the `CreateTaskRequest` before it is sent (e.g. auth for Cloud Run). See [Hooks](hooks-and-dependencies.md). |
| `client` | Override the `CloudTasksClient` (e.g. custom credentials or transport, the emulator). |
| `auto_create_queue` | Ensure the queue exists at builder creation time. Default `True`. Set it to `False` when the queue is managed elsewhere (Terraform, `gcloud`) or the service account may only enqueue tasks. |

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

Everything above except `auto_create_queue` can be overridden per call (including builder options like
`callback_base_url`) with `.options()` before calling `.delay()`:

```python
# Trigger after 2 minutes
simple_task.options(countdown=120).delay()
```

The accepted keys are typed as the [`DelayOptions` TypedDict](../api/protocols.md).

### Routers mounted under an outer prefix

FastAPI 0.137 and later preserve included routers instead of cloning their routes. A route class therefore
knows the path declared on its own router, but it cannot unambiguously infer a prefix added later — especially
because the same router can be included more than once. Put that externally visible prefix in
`callback_base_url`:

```python
service_url = "https://worker.example.com"

DelayedRoute = DelayedRouteBuilder(
    callback_base_url=f"{service_url}/tasks",
    queue_path=queue_path(...),
    pre_create_hook=oidc_delayed_hook(
        token=tasks_v2.OidcToken(
            service_account_email="tasks@example.iam.gserviceaccount.com",
            audience=service_url,
        ),
    ),
)

task_router = APIRouter(route_class=DelayedRoute, prefix="/auth")


@task_router.post("/confirm/{user_id}")
def confirm_user(user_id: str) -> None: ...


app.include_router(task_router, prefix="/tasks")
```

`confirm_user.delay(user_id="42")` now targets `https://worker.example.com/tasks/auth/confirm/42`. The OIDC
audience remains the service URL; it does not need the callback path prefix. The same rule applies to the
async and scheduled route builders.

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
| `callback_base_url` | The externally reachable URL prefix to which the scheduled route's own path is appended, including any outer `include_router()` prefix. |
| `base_url` | Legacy alias for `callback_base_url`. Pass only one of the two. |
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
