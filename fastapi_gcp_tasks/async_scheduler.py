# Standard Library Imports
from collections.abc import Callable
from typing import Any

# Third Party Imports
from fastapi.routing import APIRoute
from google.api_core.exceptions import NotFound
from google.cloud import scheduler_v1

# Imports from this repository
from fastapi_gcp_tasks.async_clients import AsyncClientProvider
from fastapi_gcp_tasks.hooks import ScheduledHook
from fastapi_gcp_tasks.scheduler import BaseScheduler

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

        if self.force or await self._has_changed(request=request):
            # Delete and create job
            await self.delete()
            client = await self.client_provider.get()
            await client.create_job(request=request, timeout=self.job_create_timeout)

    async def _has_changed(self, request: scheduler_v1.CreateJobRequest) -> bool:
        client = await self.client_provider.get()
        try:
            job = await client.get_job(name=request.job.name)
        except NotFound:
            return True
        return self._job_changed(job=job, request=request)

    async def delete(self) -> bool:
        """
        Delete the job from the scheduler.

        Returns True if the job was deleted and False if it did not exist, so it is safe
        to call from several instances at once. Any other error is raised.
        """
        client = await self.client_provider.get()
        try:
            await client.delete_job(name=self.job_id, timeout=self.job_create_timeout)
        except NotFound:
            return False
        return True
