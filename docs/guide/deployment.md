# Deploying to Cloud Run

Running on Cloud Run with authentication needs us to supply an OIDC token. To do that we can use a
[hook](hooks-and-dependencies.md).

Pre-requisites:

- Create a task queue. Copy the project id, location, and queue name.
- Deploy the worker as a service on Cloud Run and copy its URL.
- Create a service account in Cloud IAM and add the `Cloud Run Invoker` role to it.

```python
from google.cloud import tasks_v2

from fastapi_gcp_tasks import DelayedRouteBuilder
from fastapi_gcp_tasks.hooks import oidc_delayed_hook
from fastapi_gcp_tasks.utils import queue_path

# URL of the Cloud Run service
base_url = "https://hello-randomchars-el.a.run.app"

DelayedRoute = DelayedRouteBuilder(
    base_url=base_url,
    queue_path=queue_path(...),
    pre_create_hook=oidc_delayed_hook(
        token=tasks_v2.OidcToken(
            # Service account that you created
            service_account_email="fastapi-gcp-tasks@gcp-project-id.iam.gserviceaccount.com",
            audience=base_url,
        ),
    ),
)
```

Check the fleshed-out example at
[`examples/full/tasks.py`](https://github.com/SimplifyJobs/fastapi-gcp-tasks/blob/master/examples/full/tasks.py) —
it chains OIDC auth with a worker deadline, wires up the async builders, and schedules a recurring job.

If you're not running on Cloud Run and want an OAuth token instead, use `oauth_delayed_hook` /
`oauth_scheduled_hook`.

!!! tip "Autoscaling"
    With Cloud Run, your task workers autoscale based on load — and scale to zero when idle. Pair this with
    Cloud Tasks' generous free tier and the setup is usually far cheaper than an always-on celery worker and
    broker.
