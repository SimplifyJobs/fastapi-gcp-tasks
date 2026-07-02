# Hooks & dependencies

## Hooks

We might need to override things in the task being sent to Cloud Tasks or Cloud Scheduler. The
`pre_create_hook` on every route builder allows that: it receives the `CreateTaskRequest` /
`CreateJobRequest` proto just before it is sent and returns the (possibly modified) request.

Hooks included in the library:

- `oidc_delayed_hook` / `oidc_scheduled_hook` — attach an OIDC token (for Cloud Run etc).
- `oauth_delayed_hook` / `oauth_scheduled_hook` — attach an OAuth token (for non-Cloud Run targets).
- `deadline_delayed_hook` / `deadline_scheduled_hook` — change the timeout for the worker of a task.
  (This deadline is decided by the sender, not the worker.)
- `chained_hook` — compose multiple hooks: `chained_hook(hook1, hook2)`.

```python
from google.protobuf import duration_pb2

from fastapi_gcp_tasks.hooks import chained_hook, deadline_delayed_hook, oidc_delayed_hook

DelayedRoute = DelayedRouteBuilder(
    ...,
    pre_create_hook=chained_hook(
        # Add service account auth for Cloud Run
        oidc_delayed_hook(token=tasks_v2.OidcToken(...)),
        # Give the worker half an hour
        deadline_delayed_hook(duration=duration_pb2.Duration(seconds=1800)),
    ),
)
```

Writing your own hook is just writing a function:

```python
def my_hook(request: tasks_v2.CreateTaskRequest) -> tasks_v2.CreateTaskRequest:
    request.task.http_request.headers["x-my-header"] = "value"
    return request
```

Hooks are synchronous and shared between the sync and async builders. They run inline (on the event loop for
the async builders), so they must not block.

## Helper dependencies

### max_retries

Cloud Tasks retries a task until it gets a 2xx response. `max_retries` gives up after N attempts by
responding with a 200 status once the retry count is exhausted:

```python
from fastapi_gcp_tasks import max_retries


@delayed_router.post("/fail_twice", dependencies=[Depends(max_retries(2))])
async def fail_twice() -> None:
    raise Exception("nooo")
```

### CloudTasksHeaders

Typed access to the
[headers Cloud Tasks sends to your worker](https://cloud.google.com/tasks/docs/creating-http-target-tasks#handler)
(retry count, queue name, task name, eta, ...):

```python
from fastapi_gcp_tasks import CloudTasksHeaders


@delayed_router.get("/my_task")
async def my_task(ct_headers: CloudTasksHeaders = Depends()) -> None:
    print(ct_headers.queue_name)
```

See the [Dependencies API reference](../api/dependencies.md) for all fields.
