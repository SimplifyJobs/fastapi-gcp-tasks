# Standard Library Imports
from collections.abc import Callable
from typing import Any

# Third Party Imports
from fastapi.routing import APIRoute
from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import scheduler_v1

# Imports from this repository
from fastapi_gcp_tasks.async_clients import AsyncClientProvider
from fastapi_gcp_tasks.hooks import ScheduledHook
from fastapi_gcp_tasks.scheduler import _MAX_SCHEDULE_ATTEMPTS, BaseScheduler

AsyncCloudSchedulerClientFactory = Callable[[], scheduler_v1.CloudSchedulerAsyncClient]


class AsyncScheduler(BaseScheduler):
    """
    A class to schedule HTTP requests as jobs on Google Cloud Scheduler, using an async client.

    See BaseScheduler for the shared attributes.

    Attributes
    ----------
        client_provider (AsyncClientProvider): Lazy provider for the async client. Share one
            provider across schedulers so they reuse the same client and gRPC channel.

    """

    def __init__(
        self,
        *,
        route: APIRoute,
        base_url: str,
        location_path: str,
        schedule: str,
        pre_create_hook: ScheduledHook,
        client_provider: AsyncClientProvider[scheduler_v1.CloudSchedulerAsyncClient],
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
        self.client_provider = client_provider

    async def schedule(self, *args: Any, **kwargs: Any) -> None:
        """Schedule a job on Cloud Scheduler without blocking the event loop. Takes the same arguments as the endpoint."""
        request = self._build_create_job_request(values=self._bind(args, kwargs))

        replace = self.force
        for _ in range(_MAX_SCHEDULE_ATTEMPTS):
            if not replace:
                existing = await self._existing_job(request=request)
                if existing is None:
                    # Nothing to replace, so no delete: first-time scheduling only needs
                    # permission to look up and create jobs.
                    if await self._create(request=request):
                        return
                    # Another instance created the job first: look at what it created
                    continue
                if not self._job_changed(job=existing, request=request):
                    return

            # Delete and create job. The request's name is the one looked up and created,
            # and a pre-create hook may have changed it.
            await self._delete_job(name=request.job.name)
            if await self._create(request=request):
                return
            # Another instance recreated the job between our delete and our create.
            # With force we just try again, since force never reads the job. Otherwise
            # do not assume its job matches ours: compare on the next round.
            replace = self.force

        if not self.force:
            # Out of attempts, but the job that won the last race may be the one we wanted
            existing = await self._existing_job(request=request)
            if existing is not None and not self._job_changed(job=existing, request=request):
                return
        raise self._never_settled(request=request)

    async def _create(self, request: scheduler_v1.CreateJobRequest) -> bool:
        """Create the job. Returns False if another instance created it first."""
        client = await self.client_provider.get()
        try:
            await client.create_job(request=request, timeout=self.job_create_timeout)
        except AlreadyExists:
            return False
        return True

    async def _existing_job(self, request: scheduler_v1.CreateJobRequest) -> scheduler_v1.Job | None:
        client = await self.client_provider.get()
        try:
            return await client.get_job(name=request.job.name)
        except NotFound:
            return None

    async def delete(self) -> bool:
        """
        Delete the job from the scheduler.

        Returns True if the job was deleted and False if it did not exist, so it is safe
        to call from several instances at once. Any other error is raised.
        """
        return await self._delete_job(name=self.job_id)

    async def _delete_job(self, *, name: str) -> bool:
        client = await self.client_provider.get()
        try:
            await client.delete_job(name=name, timeout=self.job_create_timeout)
        except NotFound:
            return False
        return True
