# Delayed tasks

Delayed tasks are the Cloud Tasks half of the library: trigger any FastAPI endpoint later, with retries
managed by the queue.

## Defining a task

```python
from fastapi_gcp_tasks import DelayedRouteBuilder, as_delayed_task

delayed_router = APIRouter(route_class=DelayedRouteBuilder(...))


class Recipe(BaseModel):
    ingredients: list[str]


@delayed_router.post("/{restaurant}/make_dinner")
@as_delayed_task
async def make_dinner(restaurant: str, recipe: Recipe) -> None:
    # Do a ton of work here.
    ...


app.include_router(delayed_router)
```

Because the task is a FastAPI endpoint, everything FastAPI offers works: path/query/header parameters,
Pydantic bodies, `Depends`, middlewares, and telemetry.

## Triggering

```python
make_dinner.delay(restaurant="Taj", recipe=Recipe(ingredients=["Pav", "Bhaji"]))
```

`.delay()` takes the same (keyword) arguments as the endpoint, validates them, builds the full task URL, and
creates the task on Cloud Tasks. The return value of the endpoint is meaningless to the queue — only the
HTTP status matters (2xx acknowledges the task; anything else retries it).

To trigger 30 minutes later:

```python
make_dinner.options(countdown=1800).delay(restaurant="Taj", recipe=Recipe(ingredients=["Pav", "Bhaji"]))
```

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
make_dinner.options(task_id=f"dinner-{order_id}").delay(...)
```

!!! note
    Named task deduplication is not supported by the local emulator, and Cloud Tasks raises
    `google.api_core.exceptions.AlreadyExists` when a task id is reused.

## Retries

Cloud Tasks retries a task until it responds with a 2xx status. To cap retries from the worker side, use the
[`max_retries` dependency](hooks-and-dependencies.md#max_retries).

See [Configuration](configuration.md) for every option accepted by `DelayedRouteBuilder`, `.options()`, and
`task_default_options`.
