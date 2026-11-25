---
description: >-
  Run FastAPI endpoints on a cron schedule with Google Cloud Scheduler — a serverless
  replacement for celery beat periodic tasks.
---

# Scheduled tasks

Scheduled tasks are the Cloud Scheduler half of the library: run any FastAPI endpoint on a cron schedule —
a replacement for celery beat.

## Defining and scheduling

```python
from fastapi_gcp_tasks import ScheduledRouteBuilder, as_scheduled_task

scheduled_router = APIRouter(route_class=ScheduledRouteBuilder(...))


class Recipe(BaseModel):
    ingredients: list[str]


@scheduled_router.post("/pretzel_day")
@as_scheduled_task
async def pretzel_day(recipe: Recipe) -> None:
    # Everyone gets one free soft pretzel
    ...


app.include_router(scheduled_router)

# Every Friday at 9AM in Scranton, it's Pretzel Day.
pretzel_day.scheduler(
    name="pretzel-day-9AM-scranton",
    schedule="0 9 * * 5",
    time_zone="America/New_York",
).schedule(recipe=Recipe(ingredients=["Sweet glaze", "Cinnamon sugar"]))
```

`.scheduler(...)` configures the job (name, cron schedule, time zone, retry config); `.schedule(...)` takes
the endpoint's own arguments, which become the job's HTTP body/params under the
[same rules as `.delay()`](delayed-tasks.md#what-you-can-pass).

## Idempotent job creation

`.schedule()` compares the job it is about to create against the existing job with the same name and only
recreates it when something changed, so it is safe to call at startup on every deploy and from multiple
instances. Pass `force=True` to always recreate.

If another instance creates or replaces the same job at the same moment, `.schedule()` compares its job with
the one that won and replaces it only if they differ. It raises `AlreadyExists` if the job keeps being
recreated with a different definition. With `force=True` it never reads the job, so it deletes and creates
again instead of comparing, and raises `AlreadyExists` if it keeps losing.

## Deleting a job

```python
pretzel_day.scheduler(name="pretzel-day-9AM-scranton", schedule="0 9 * * 5").delete()
```

`.delete()` returns `True` when the job was deleted and `False` when there was no such job, so it is safe to
call from several instances. Any other failure, such as missing permissions, is raised.

See [Configuration](configuration.md#scheduledroutebuilder) for all options, and
[Async usage](async.md) for `AsyncScheduledRouteBuilder`, whose `.schedule()`/`.delete()` are coroutines.
