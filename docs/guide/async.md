# Async usage

`DelayedRouteBuilder`'s `.delay()` makes a blocking gRPC call. Called from an async endpoint, it stalls the
event loop until Cloud Tasks responds. `AsyncDelayedRouteBuilder` uses the native `CloudTasksAsyncClient`
instead, so triggering a task is a proper coroutine:

```python
from fastapi_gcp_tasks import AsyncDelayedRouteBuilder, as_async_delayed_task

async_delayed_router = APIRouter(route_class=AsyncDelayedRouteBuilder(...))


@async_delayed_router.post("/{branch}/make_chili")
@as_async_delayed_task
async def make_chili(branch: str, recipe: Recipe) -> None: ...


app.include_router(async_delayed_router)

# In an async context (endpoint, lifespan, etc):
await make_chili.delay(branch="Scranton", recipe=Recipe(ingredients=["Ground beef", "Undercooked onions"]))
await make_chili.options(countdown=1800).delay(branch="Scranton", recipe=Recipe(ingredients=["Ground beef", "Undercooked onions"]))
```

Similarly, `AsyncScheduledRouteBuilder` provides awaitable `.schedule()` and `.delete()` — useful when
creating Cloud Scheduler jobs dynamically from request handlers. Since it can't run at module import time
like the sync version, await it from a lifespan (or a handler):

```python
from contextlib import asynccontextmanager

from fastapi_gcp_tasks import AsyncScheduledRouteBuilder, as_async_scheduled_task

async_scheduled_router = APIRouter(route_class=AsyncScheduledRouteBuilder(...))


@async_scheduled_router.post("/pretzel_day")
@as_async_scheduled_task
async def pretzel_day(recipe: Recipe) -> None: ...


@asynccontextmanager
async def lifespan(app: FastAPI):
    await pretzel_day.scheduler(
        name="pretzel-day-9AM-scranton",
        schedule="0 9 * * 5",
        time_zone="America/New_York",
    ).schedule(recipe=Recipe(ingredients=["Sweet glaze", "Cinnamon sugar"]))
    yield
```

## Things to know about the async builders

### The client is created lazily

grpc.aio clients bind to the event loop that is running when they are constructed, so the builder resolves
its client on the first awaited call, inside your app's loop. `client` accepts a client instance, a
zero-argument factory returning one, or `None` (default credentials). If your client needs custom
construction — like the local emulator — pass a factory:

```python
client = lambda: async_emulator_client()
```

### The queue is not auto-created by default

Unlike `DelayedRouteBuilder`, `auto_create_queue` defaults to `False` so no unexpected RPC runs inside a
request handler. Either ensure the queue from your lifespan with the `ensure_queue_async` util
(recommended), or opt in with `auto_create_queue=True` to ensure it lazily on the first `.delay()`:

```python
from contextlib import asynccontextmanager

from fastapi_gcp_tasks.utils import ensure_queue_async


@asynccontextmanager
async def lifespan(app: FastAPI):
    await ensure_queue_async(client=my_async_client, path=MY_QUEUE_PATH)
    yield
```

### Hooks are unchanged

The same (synchronous) `pre_create_hook`s work with both sync and async builders — they are pure in-memory
mutations of the request proto and run inline on the event loop, so they must not block.
