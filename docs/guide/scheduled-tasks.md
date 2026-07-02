# Scheduled tasks

Scheduled tasks are the Cloud Scheduler half of the library: run any FastAPI endpoint on a cron schedule —
a replacement for celery beat.

## Defining and scheduling

```python
from fastapi_gcp_tasks import ScheduledRouteBuilder, as_scheduled_task

scheduled_router = APIRouter(route_class=ScheduledRouteBuilder(...))


class Recipe(BaseModel):
    ingredients: list[str]


@scheduled_router.post("/home_cook")
@as_scheduled_task
async def home_cook(recipe: Recipe) -> None:
    # Make my own food
    ...


app.include_router(scheduled_router)

# Make my own breakfast every morning at 7AM IST.
home_cook.scheduler(
    name="test-home-cook-at-7AM-IST",
    schedule="0 7 * * *",
    time_zone="Asia/Kolkata",
).schedule(recipe=Recipe(ingredients=["Milk", "Cereal"]))
```

`.scheduler(...)` configures the job (name, cron schedule, time zone, retry config); `.schedule(...)` takes
the endpoint's own keyword arguments, which become the job's HTTP body/params.

## Idempotent job creation

`.schedule()` compares the job it is about to create against the existing job with the same name and only
recreates it when something changed, so it is safe to call at startup on every deploy and from multiple
instances. Pass `force=True` to always recreate.

## Deleting a job

```python
home_cook.scheduler(name="test-home-cook-at-7AM-IST", schedule="0 7 * * *").delete()
```

See [Configuration](configuration.md#scheduledroutebuilder) for all options, and
[Async usage](async.md) for `AsyncScheduledRouteBuilder`, whose `.schedule()`/`.delete()` are coroutines.
