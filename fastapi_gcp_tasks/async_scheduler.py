# Standard Library Imports
from typing import Any, Callable

# Third Party Imports
from fastapi.routing import APIRoute
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

    async def schedule(self, **kwargs: Any) -> None:
        """Schedule a job on Cloud Scheduler without blocking the event loop."""
        request = self._build_create_job_request(values=kwargs)

        if self.force or await self._has_changed(request=request):
            # Delete and create job
            await self.delete()
            client = await self.client_provider.get()
            await client.create_job(request=request, timeout=self.job_create_timeout)

    async def _has_changed(self, request: scheduler_v1.CreateJobRequest) -> bool:
        try:
            client = await self.client_provider.get()
            job = await client.get_job(name=request.job.name)
            return self._job_changed(job=job, request=request)
        # TODO: replace this with a more specific exception
        except Exception:  # noqa: BLE001
            return True

    async def delete(self) -> bool | Exception:
        """Delete the job from the scheduler if it exists."""
        # We return true or exception because you could have the delete code on multiple instances
        try:
            client = await self.client_provider.get()
            await client.delete_job(name=self.job_id, timeout=self.job_create_timeout)
            return True
        # TODO: replace this with a more specific exception. we may also just raise the exception here?
        except Exception as ex:  # noqa: BLE001
            return ex
