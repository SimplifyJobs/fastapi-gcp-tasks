# Standard Library Imports
from uuid import uuid4

# Third Party Imports
from fastapi import FastAPI, Response, status
from google.api_core.exceptions import AlreadyExists

# Imports from this repository
from examples.full.serializer import Payload
from examples.full.settings import IS_LOCAL
from examples.full.tasks import fail_twice, hello, hello_async

app = FastAPI()

task_id = str(uuid4())


@app.get("/basic")
async def basic() -> dict[str, str]:
    hello.delay(p=Payload(message="Basic task"))
    return {"message": "Basic hello task scheduled"}


@app.get("/async_basic")
async def async_basic() -> dict[str, str]:
    await hello_async.delay(p=Payload(message="Async basic task"))
    return {"message": "Async basic hello task scheduled"}


@app.get("/async_with_countdown")
async def async_with_countdown() -> dict[str, str]:
    await hello_async.options(countdown=5).delay(p=Payload(message="Async countdown task"))
    return {"message": "Async countdown hello task scheduled"}


@app.get("/with_countdown")
async def with_countdown() -> dict[str, str]:
    hello.options(countdown=5).delay(p=Payload(message="Countdown task"))
    return {"message": "Countdown hello task scheduled"}


@app.get("/deduped")
async def deduped(response: Response) -> dict[str, str]:
    # Note: this does not work with cloud-tasks-emulator.
    try:
        hello.options(task_id=task_id).delay(p=Payload(message="Deduped task"))
        return {"message": "Deduped hello task scheduled"}
    except AlreadyExists as e:
        response.status_code = status.HTTP_409_CONFLICT
        return {"error": "Could not schedule task.", "reason": str(e)}


@app.get("/fail")
async def fail() -> dict[str, str]:
    fail_twice.delay()
    return {"message": "The triggered task will fail twice and then be marked done automatically"}


# We can use a trick on local to get all tasks on the same process as the main server.
# In a deployed environment, we'd really want to run 2 separate processes
if IS_LOCAL:
    # Imports from this repository
    from examples.full.tasks import app as task_app

    app.mount("/_fastapi_cloud_tasks", task_app)
