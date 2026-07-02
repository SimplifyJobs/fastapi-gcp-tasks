# Route builders

The four route builders return an `APIRoute` subclass to pass as `route_class=` to an `APIRouter`. Endpoints
registered on that router gain `.delay`/`.options` (delayed) or `.scheduler` (scheduled) methods.

::: fastapi_gcp_tasks.delayed_route.DelayedRouteBuilder

::: fastapi_gcp_tasks.async_delayed_route.AsyncDelayedRouteBuilder

::: fastapi_gcp_tasks.scheduled_route.ScheduledRouteBuilder

::: fastapi_gcp_tasks.async_scheduled_route.AsyncScheduledRouteBuilder

::: fastapi_gcp_tasks.decorators.task_default_options
