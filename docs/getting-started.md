# Getting started

## Installation

```sh
pip install fastapi-gcp-tasks
```

Python 3.11+ is required.

## Your first delayed task

A delayed task is a plain FastAPI endpoint registered on a router whose `route_class` comes from
`DelayedRouteBuilder`. That gives the endpoint a `.delay()` method:

```python
import logging
import os

from fastapi import FastAPI
from fastapi.routing import APIRouter
from pydantic import BaseModel

from fastapi_gcp_tasks import DelayedRouteBuilder, as_delayed_task
from fastapi_gcp_tasks.utils import emulator_client, queue_path

IS_LOCAL = os.getenv("IS_LOCAL", "true").lower() == "true"

# For local development, point the client at the emulator
client = emulator_client() if IS_LOCAL else None

DelayedRoute = DelayedRouteBuilder(
    client=client,
    # Base URL where the task server is hosted
    base_url="http://localhost:8000",
    # Full queue path where tasks will be sent
    queue_path=queue_path(
        project="gcp-project-id",
        location="us-central1",
        queue="test-queue",
    ),
)

delayed_router = APIRouter(route_class=DelayedRoute, prefix="/delayed")

logger = logging.getLogger("uvicorn")


class Payload(BaseModel):
    message: str


@delayed_router.post("/hello")
@as_delayed_task  # optional: makes .delay statically visible to type checkers
async def hello(p: Payload = Payload(message="Default")) -> None:
    logger.warning(f"Hello task ran with payload: {p.message}")


app = FastAPI()


# A plain `def` endpoint: the sync `.delay()` makes a blocking gRPC call, so let
# FastAPI run it in the threadpool (or see the Async usage guide for `await .delay()`).
@app.get("/trigger")
def trigger() -> dict[str, str]:
    hello.delay(p=Payload(message="Triggered task"))
    return {"message": "Hello task triggered"}


app.include_router(delayed_router)
```

## Running locally

There is no local Cloud Tasks service, so use the open-source
[cloud-tasks-emulator](https://github.com/aertje/cloud-tasks-emulator) (alternatively, install ngrok and
forward the server's port to use the real Cloud Tasks).

Start the emulator in one terminal:

```sh
cloud-tasks-emulator
```

Save the snippet as `main.py` and start it on port 8000 so Cloud Tasks can reach it:

```sh
uvicorn main:app --reload --port 8000
```

(If you cloned the repository instead, the checked-in example runs with
`uvicorn examples.simple.main:app --reload --port 8000`.)

Trigger the task from another terminal:

```sh
curl http://localhost:8000/trigger
```

Check the server logs — you should see:

```
WARNING:  Hello task ran with payload: Triggered task
```

The complete working example lives at
[`examples/simple/main.py`](https://github.com/SimplifyJobs/fastapi-gcp-tasks/blob/master/examples/simple/main.py).
In the real world you'd run the task worker as a separate process from the service that triggers tasks.

## Next steps

- [Delayed tasks](guide/delayed-tasks.md) — countdowns, deduplication, and per-call overrides.
- [Scheduled tasks](guide/scheduled-tasks.md) — recurring jobs on a cron schedule.
- [Async usage](guide/async.md) — `await .delay()` without blocking the event loop.
- [Deploying to Cloud Run](guide/deployment.md) — OIDC auth with hooks.
