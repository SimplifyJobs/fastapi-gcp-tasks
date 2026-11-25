# Standard Library Imports
import copy
from collections.abc import Iterable
from typing import Any

# Third Party Imports
from fastapi.routing import APIRoute
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import scheduler_v1
from google.protobuf import duration_pb2

# Imports from this repository
from fastapi_gcp_tasks.exception import BadMethodError
from fastapi_gcp_tasks.hooks import ScheduledHook
from fastapi_gcp_tasks.requester import Requester

# How many times schedule() looks again after losing a create race to another instance
_MAX_SCHEDULE_ATTEMPTS = 3


class BaseScheduler(Requester):
    """
    Shared logic to build Cloud Scheduler job requests from FastAPI routes.

    Attributes
    ----------
        retry_config (scheduler_v1.RetryConfig): Configuration for retrying failed jobs.
        job_id (str): The unique identifier for the job.
        time_zone (str): The time zone for the job schedule.
        location_path (str): The location path for the job.
        cron_schedule (str): The cron schedule for the job.
        job_create_timeout (float): Timeout for creating the job.
        method (scheduler_v1.HttpMethod): The HTTP method for the job.
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
        # Path helpers are staticmethods shared by the sync and async clients,
        # so we don't need a client instance here.
        location_parts = scheduler_v1.CloudSchedulerClient.parse_common_location_path(location_path)

        self.job_id = scheduler_v1.CloudSchedulerClient.job_path(job=name, **location_parts)
        self.time_zone = time_zone

        self.location_path = location_path
        self.cron_schedule = schedule
        self.job_create_timeout = job_create_timeout

        self.method = _scheduler_method(route.methods)
        self.pre_create_hook = pre_create_hook
        self.force = force

    def _build_create_job_request(self, *, values: dict[str, Any]) -> scheduler_v1.CreateJobRequest:
        """Build the CreateJobRequest (including the pre-create hook) for the given endpoint arguments."""
        # Create http request
        http_target = scheduler_v1.HttpTarget()
        http_target.http_method = self.method
        http_target.uri = self._url(values=values)
        http_target.headers = self._headers(values=values)

        body = self._body(values=values)
        if body:
            http_target.body = body

        # Scheduled the task
        job = scheduler_v1.Job(
            name=self.job_id,
            http_target=http_target,
            schedule=self.cron_schedule,
            retry_config=self.retry_config,
            time_zone=self.time_zone,
        )

        request = scheduler_v1.CreateJobRequest(parent=self.location_path, job=job)

        return self.pre_create_hook(request)

    @staticmethod
    def _never_settled(*, request: scheduler_v1.CreateJobRequest) -> AlreadyExists:
        # google-api-core exceptions ship without annotations
        return AlreadyExists(  # type: ignore[no-untyped-call]
            f"Job {request.job.name} kept being recreated with a different definition by another process "
            f"({_MAX_SCHEDULE_ATTEMPTS} attempts)"
        )

    @staticmethod
    def _job_changed(*, job: scheduler_v1.Job, request: scheduler_v1.CreateJobRequest) -> bool:
        """Compare an existing job against the job we want to create, ignoring output-only fields."""
        # Remove things that are either output only or GCP adds by default
        job.user_update_time = None  # type: ignore[assignment]
        job.state = None  # type: ignore[assignment]
        job.status = None
        job.last_attempt_time = None  # type: ignore[assignment]
        job.schedule_time = None  # type: ignore[assignment]
        # Strip User-Agent from BOTH sides: GCP stamps it onto stored jobs, and a
        # pre-create hook may set one on ours — an asymmetric strip would make
        # identical jobs always compare as changed. Compare against a copy so the
        # request that is actually sent to create_job keeps its headers.
        desired = copy.deepcopy(request.job)
        job.http_target.headers.pop("User-Agent", None)
        desired.http_target.headers.pop("User-Agent", None)
        # Proto compare works directly with `__eq__`
        return job != desired


class Scheduler(BaseScheduler):
    """
    A class to schedule HTTP requests as jobs on Google Cloud Scheduler.

    See BaseScheduler for the shared attributes.

    Attributes
    ----------
        client (scheduler_v1.CloudSchedulerClient): The Cloud Scheduler client.

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
        super().__init__(
            route=route,
            base_url=base_url,
            location_path=location_path,
            schedule=schedule,
            pre_create_hook=pre_create_hook,
            name=name,
            job_create_timeout=job_create_timeout,
            retry_config=retry_config,
            time_zone=time_zone,
            force=force,
        )
        self.client = client

    def schedule(self, *args: Any, **kwargs: Any) -> None:
        """Schedule a job on Cloud Scheduler. Takes the same arguments as the endpoint."""
        request = self._build_create_job_request(values=self._bind(args, kwargs))

        replace = self.force
        for _ in range(_MAX_SCHEDULE_ATTEMPTS):
            if not replace:
                existing = self._existing_job(request=request)
                if existing is None:
                    # Nothing to replace, so no delete: first-time scheduling only needs
                    # permission to look up and create jobs.
                    if self._create(request=request):
                        return
                    # Another instance created the job first: look at what it created
                    continue
                if not self._job_changed(job=existing, request=request):
                    return

            # Delete and create job
            self.delete()
            if self._create(request=request):
                return
            # Another instance recreated the job between our delete and our create.
            # With force we just try again, since force never reads the job. Otherwise
            # do not assume its job matches ours: compare on the next round.
            replace = self.force

        if not self.force:
            # Out of attempts, but the job that won the last race may be the one we wanted
            existing = self._existing_job(request=request)
            if existing is not None and not self._job_changed(job=existing, request=request):
                return
        raise self._never_settled(request=request)

    def _create(self, request: scheduler_v1.CreateJobRequest) -> bool:
        """Create the job. Returns False if another instance created it first."""
        try:
            self.client.create_job(request=request, timeout=self.job_create_timeout)
        except AlreadyExists:
            return False
        return True

    def _existing_job(self, request: scheduler_v1.CreateJobRequest) -> scheduler_v1.Job | None:
        try:
            return self.client.get_job(name=request.job.name)
        except NotFound:
            return None

    def delete(self) -> bool:
        """
        Delete the job from the scheduler.

        Returns True if the job was deleted and False if it did not exist, so it is safe
        to call from several instances at once. Any other error is raised.
        """
        try:
            self.client.delete_job(name=self.job_id, timeout=self.job_create_timeout)
        except NotFound:
            return False
        return True


def _scheduler_method(methods: Iterable[str] | None) -> scheduler_v1.HttpMethod:
    method_map = {
        "POST": scheduler_v1.HttpMethod.POST,
        "GET": scheduler_v1.HttpMethod.GET,
        "HEAD": scheduler_v1.HttpMethod.HEAD,
        "PUT": scheduler_v1.HttpMethod.PUT,
        "DELETE": scheduler_v1.HttpMethod.DELETE,
        "PATCH": scheduler_v1.HttpMethod.PATCH,
        "OPTIONS": scheduler_v1.HttpMethod.OPTIONS,
    }
    methods = list(methods or [])
    # Only crash if we're being bound
    if not methods:
        raise BadMethodError("Can't schedule task without a method")
    if len(methods) > 1:
        raise BadMethodError("Can't schedule task with multiple methods")
    method = method_map.get(methods[0])
    if method is None:
        raise BadMethodError(f"Unknown method {methods[0]}")
    return scheduler_v1.HttpMethod(method)
