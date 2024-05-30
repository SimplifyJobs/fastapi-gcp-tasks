# Standard Library Imports
from typing import Any, Iterable

# Third Party Imports
from fastapi.routing import APIRoute
from google.cloud import scheduler_v1
from google.protobuf import duration_pb2

# Imports from this repository
from fastapi_gcp_tasks.exception import BadMethodError
from fastapi_gcp_tasks.hooks import ScheduledHook
from fastapi_gcp_tasks.requester import Requester


class Scheduler(Requester):
    """
    A class to schedule HTTP requests as jobs on Google Cloud Scheduler.

    Attributes
    ----------
        retry_config (scheduler_v1.RetryConfig): Configuration for retrying failed jobs.
        job_id (str): The unique identifier for the job.
        time_zone (str): The time zone for the job schedule.
        location_path (str): The location path for the job.
        cron_schedule (str): The cron schedule for the job.
        job_create_timeout (float): Timeout for creating the job.
        method (scheduler_v1.HttpMethod): The HTTP method for the job.
        client (scheduler_v1.CloudSchedulerClient): The Cloud Scheduler client.
        pre_create_hook (ScheduledHook): Hook to be called before creating the job.
        force (bool): Whether to force create the job if it already exists.

    """

    def __init__(
        self,
        *,
        route: APIRoute,
        base_url: str,
        location_path: str,
        schedule: str,
        client: scheduler_v1.CloudSchedulerClient,
        pre_create_hook: ScheduledHook,
        name: str = "",
        job_create_timeout: float = 10.0,
        retry_config: scheduler_v1.RetryConfig | None = None,
        time_zone: str = "UTC",
        force: bool = False,
    ) -> None:
        super().__init__(route=route, base_url=base_url)
        if not name:
            name = route.unique_id

        if retry_config is None:
            retry_config = scheduler_v1.RetryConfig(
                retry_count=5,
                max_retry_duration=duration_pb2.Duration(seconds=0),
                min_backoff_duration=duration_pb2.Duration(seconds=5),
                max_backoff_duration=duration_pb2.Duration(seconds=120),
                max_doublings=5,
            )

        self.retry_config = retry_config
        location_parts = client.parse_common_location_path(location_path)

        self.job_id = client.job_path(job=name, **location_parts)
        self.time_zone = time_zone

        self.location_path = location_path
        self.cron_schedule = schedule
        self.job_create_timeout = job_create_timeout

        self.method = _scheduler_method(route.methods)
        self.client = client
        self.pre_create_hook = pre_create_hook
        self.force = force

    def schedule(self, **kwargs: Any) -> None:
        """Schedule a job on Cloud Scheduler."""
        # Create http request
        request = scheduler_v1.HttpTarget()
        request.http_method = self.method
        request.uri = self._url(values=kwargs)
        request.headers = self._headers(values=kwargs)

        body = self._body(values=kwargs)
        if body:
            request.body = body

        # Scheduled the task
        job = scheduler_v1.Job(
            name=self.job_id,
            http_target=request,
            schedule=self.cron_schedule,
            retry_config=self.retry_config,
            time_zone=self.time_zone,
        )

        request = scheduler_v1.CreateJobRequest(parent=self.location_path, job=job)

        request = self.pre_create_hook(request)

        if self.force or self._has_changed(request=request):
            # Delete and create job
            self.delete()
            self.client.create_job(request=request, timeout=self.job_create_timeout)

    def _has_changed(self, request: scheduler_v1.CreateJobRequest) -> bool:
        try:
            job = self.client.get_job(name=request.job.name)
            # Remove things that are either output only or GCP adds by default
            job.user_update_time = None  # type: ignore[assignment]
            job.state = None  # type: ignore[assignment]
            job.status = None
            job.last_attempt_time = None  # type: ignore[assignment]
            job.schedule_time = None  # type: ignore[assignment]
            del job.http_target.headers["User-Agent"]
            # Proto compare works directly with `__eq__`
            return job != request.job
        # TODO: replace this with a more specific exception
        except Exception:  # noqa: BLE001
            return True
        return False

    def delete(self) -> bool | Exception:
        """Delete the job from the scheduler if it exists."""
        # We return true or exception because you could have the delete code on multiple instances
        try:
            self.client.delete_job(name=self.job_id, timeout=self.job_create_timeout)
            return True
        # TODO: replace this with a more specific exception. we may also just raise the exception here?
        except Exception as ex:  # noqa: BLE001
            return ex


def _scheduler_method(methods: Iterable[str]) -> scheduler_v1.HttpMethod:
    method_map = {
        "POST": scheduler_v1.HttpMethod.POST,
        "GET": scheduler_v1.HttpMethod.GET,
        "HEAD": scheduler_v1.HttpMethod.HEAD,
        "PUT": scheduler_v1.HttpMethod.PUT,
        "DELETE": scheduler_v1.HttpMethod.DELETE,
        "PATCH": scheduler_v1.HttpMethod.PATCH,
        "OPTIONS": scheduler_v1.HttpMethod.OPTIONS,
    }
    methods = list(methods)
    # Only crash if we're being bound
    if len(methods) > 1:
        raise BadMethodError("Can't schedule task with multiple methods")
    method = method_map.get(methods[0])
    if method is None:
        raise BadMethodError(f"Unknown method {methods[0]}")
    return scheduler_v1.HttpMethod(method)
