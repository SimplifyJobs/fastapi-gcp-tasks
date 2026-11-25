---
description: >-
  Trigger any FastAPI endpoint later with Google Cloud Tasks: .delay(), countdowns,
  deduplication, retries, and how arguments become the task's HTTP request.
---

# Delayed tasks

Delayed tasks are the Cloud Tasks half of the library: trigger any FastAPI endpoint later, with retries
managed by the queue.

## Defining a task

```python
from fastapi_gcp_tasks import DelayedRouteBuilder, as_delayed_task

delayed_router = APIRouter(route_class=DelayedRouteBuilder(...))


class Recipe(BaseModel):
    ingredients: list[str]


@delayed_router.post("/{branch}/make_chili")
@as_delayed_task
async def make_chili(branch: str, recipe: Recipe) -> None:
    # Do a ton of work here. The secret is to undercook the onions.
    ...


app.include_router(delayed_router)
```

Because the task is a FastAPI endpoint, everything FastAPI offers works: path/query/header parameters,
Pydantic bodies, `Depends`, middlewares, and telemetry.

## Triggering

```python
make_chili.delay(branch="Scranton", recipe=Recipe(ingredients=["Ground beef", "Undercooked onions"]))
```

`.delay()` takes the same arguments as the endpoint (by keyword or by position), validates them, builds the
full task URL, and creates the task on Cloud Tasks. The return value of the endpoint is meaningless to the
queue — only the HTTP status matters (2xx acknowledges the task; anything else retries it).

To trigger 30 minutes later:

```python
make_chili.options(countdown=1800).delay(branch="Scranton", recipe=Recipe(ingredients=["Ground beef", "Undercooked onions"]))
```

## What you can pass

Each argument is sent the way FastAPI will read it back on the worker:

| Endpoint parameter | Sent as |
| --- | --- |
| Path parameter | Percent-encoded path segment. |
| Query parameter | Query string. Lists repeat the key, enums send their value, dates use ISO 8601. |
| `Header()` parameter | Request header. Pass it by its Python name: `x_request_id="..."` is sent as `x-request-id`. A list header can carry one value, because a task request sends each header once. |
| `Cookie()` parameter | `Cookie` request header. |
| One Pydantic body | The JSON body. |
| Several bodies, or `Body(embed=True)` | One JSON object keyed by parameter name. |

A few rules keep mistakes at the call site instead of on the worker:

- **Arguments you leave out fall back to the endpoint's default.** A `None` default is not sent at all; any
  other default is sent explicitly. For a body parameter that accepts `None`, passing `None` sends JSON `null`,
  which is different from leaving it out.
- **An empty list cannot be expressed in a query string or header.** Passing one raises `ValueError`, unless
  the endpoint's own default is also empty, in which case the key is simply left out.
- **Unknown arguments raise `TypeError`**, as they would in a normal function call. So does a value for an
  argument the worker resolves itself, such as `db: Session = Depends(get_db)`.
- **Values are validated** against the endpoint's annotations before the task is created. A missing required
  argument raises `MissingParamError`; a path value that is empty or contains `/` raises `ValueError` (declare
  the segment as `{name:path}` to allow slashes).
- **Query, header and cookie parameters owned by a dependency are optional here.** If `Depends(verify_token)`
  reads an `Authorization` header, `.delay()` does not ask for it, because a [hook](hooks-and-dependencies.md)
  or Cloud Tasks' own OIDC token usually supplies it. You can still pass such a parameter by name when you need
  to. Body parameters are different: the JSON body is one document only the caller can supply, so a required
  body parameter is required wherever it is declared.
- **`Form()` and `File()` parameters are not supported.** Task bodies are always sent as JSON.

## Per-endpoint defaults

Set default options once with the `task_default_options` decorator instead of at every call site:

```python
from fastapi_gcp_tasks import task_default_options


# Trigger after 5 minutes by default
@delayed_router.get("/simple_task")
@task_default_options(countdown=300)
def simple_task() -> None: ...
```

## Deduplication

Pass a `task_id` to make Cloud Tasks queue a given task at most once:

```python
make_chili.options(task_id=f"chili-{party_id}").delay(...)
```

!!! note
    Named task deduplication is not supported by the local emulator, and Cloud Tasks raises
    `google.api_core.exceptions.AlreadyExists` when a task id is reused.

## Retries

Cloud Tasks retries a task until it responds with a 2xx status. To cap retries from the worker side, use the
[`max_retries` dependency](hooks-and-dependencies.md#max_retries).

See [Configuration](configuration.md) for every option accepted by `DelayedRouteBuilder`, `.options()`, and
`task_default_options`.
