# Standard Library Imports
import logging

# Third Party Imports
from fastapi import Depends, FastAPI
from fastapi.routing import APIRouter
from google.cloud import tasks_v2
from google.protobuf import duration_pb2

# Imports from this repository
from examples.full.serializer import Payload
from examples.full.settings import (
    CLOUD_TASKS_EMULATOR_URL,
    IS_LOCAL,
    SCHEDULED_LOCATION_PATH,
    SCHEDULED_OIDC_TOKEN,
    TASK_LISTENER_BASE_URL,
    TASK_OIDC_TOKEN,
    TASK_QUEUE_PATH,
)
from fastapi_gcp_tasks import (
    AsyncDelayedRouteBuilder,
    DelayedRouteBuilder,
    as_async_delayed_task,
    as_delayed_task,
    as_scheduled_task,
)
from fastapi_gcp_tasks.dependencies import max_retries
from fastapi_gcp_tasks.hooks import (
    chained_hook,
    deadline_delayed_hook,
    deadline_scheduled_hook,
    oidc_delayed_hook,
    oidc_scheduled_hook,
)
from fastapi_gcp_tasks.scheduled_route import ScheduledRouteBuilder
from fastapi_gcp_tasks.utils import async_emulator_client, emulator_client

app = FastAPI()


logger = logging.getLogger("uvicorn")

delayed_client = None
if IS_LOCAL:
    delayed_client = emulator_client(host=CLOUD_TASKS_EMULATOR_URL)

DelayedRoute = DelayedRouteBuilder(
    client=delayed_client,
    callback_base_url=TASK_LISTENER_BASE_URL,
    queue_path=TASK_QUEUE_PATH,
    # Chain multiple hooks together
    pre_create_hook=chained_hook(
        # Add service account for cloud run
        oidc_delayed_hook(
            token=TASK_OIDC_TOKEN,
        ),
        # Wait for half an hour
        deadline_delayed_hook(duration=duration_pb2.Duration(seconds=1800)),
    ),
)

# No Cloud Scheduler emulator exists, so pass a dummy client when running locally
# to avoid requiring GCP credentials. The client is never used in local mode
# because the .schedule() call below is guarded by `if not IS_LOCAL`.
scheduled_client = None
if IS_LOCAL:
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import scheduler_v1

    scheduled_client = scheduler_v1.CloudSchedulerClient(credentials=AnonymousCredentials())

ScheduledRoute = ScheduledRouteBuilder(
    client=scheduled_client,
    callback_base_url=TASK_LISTENER_BASE_URL,
    location_path=SCHEDULED_LOCATION_PATH,
    pre_create_hook=chained_hook(
        # Add service account for cloud run
        oidc_scheduled_hook(
            token=SCHEDULED_OIDC_TOKEN,
        ),
        # Wait for half an hour
        deadline_scheduled_hook(duration=duration_pb2.Duration(seconds=1800)),
    ),
)


# The async client binds to the running event loop, so pass a factory that is
# resolved lazily on the first awaited .delay() instead of a client instance.
def _local_async_delayed_client() -> tasks_v2.CloudTasksAsyncClient:
    return async_emulator_client(host=CLOUD_TASKS_EMULATOR_URL)


AsyncDelayedRoute = AsyncDelayedRouteBuilder(
    client=_local_async_delayed_client if IS_LOCAL else None,
    callback_base_url=TASK_LISTENER_BASE_URL,
    queue_path=TASK_QUEUE_PATH,
    auto_create_queue=True,
    pre_create_hook=chained_hook(
        # Add service account for cloud run
        oidc_delayed_hook(
            token=TASK_OIDC_TOKEN,
        ),
        # Wait for half an hour
        deadline_delayed_hook(duration=duration_pb2.Duration(seconds=1800)),
    ),
)

delayed_router = APIRouter(route_class=DelayedRoute, prefix="/delayed")


@delayed_router.post("/hello")
@as_delayed_task
async def hello(p: Payload = Payload(message="Default")) -> None:
    message = f"Hello task ran with payload: {p.message}"
    logger.warning(message)


@delayed_router.post("/fail_twice", dependencies=[Depends(max_retries(2))])
@as_delayed_task
async def fail_twice() -> None:
    raise Exception("nooo")


async_delayed_router = APIRouter(route_class=AsyncDelayedRoute, prefix="/async_delayed")


@async_delayed_router.post("/hello")
@as_async_delayed_task
async def hello_async(p: Payload = Payload(message="Default")) -> None:
    message = f"Async hello task ran with payload: {p.message}"
    logger.warning(message)


scheduled_router = APIRouter(route_class=ScheduledRoute, prefix="/scheduled")


@scheduled_router.post("/timed_hello")
@as_scheduled_task
async def scheduled_hello(p: Payload = Payload(message="Default")) -> dict[str, str]:
    message = f"Scheduled hello task ran with payload: {p.message}"
    logger.warning(message)
    return {"message": message}


# We want to schedule tasks only in a deployed environment
if not IS_LOCAL:
    scheduled_hello.scheduler(
        name="testing-examples-scheduled-hello",
        schedule="*/5 * * * *",
        time_zone="Asia/Kolkata",
    ).schedule(p=Payload(message="Scheduled"))

app.include_router(delayed_router)
app.include_router(async_delayed_router)
app.include_router(scheduled_router)
