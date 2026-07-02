# Standard Library Imports
import asyncio
from typing import Any, Callable

# Third Party Imports
from fastapi.routing import APIRoute
from google.cloud import tasks_v2

# Imports from this repository
from fastapi_gcp_tasks.async_clients import AsyncClientProvider
from fastapi_gcp_tasks.delayer import BaseDelayer
from fastapi_gcp_tasks.hooks import DelayedTaskHook
from fastapi_gcp_tasks.utils import ensure_queue_async

AsyncCloudTasksClientFactory = Callable[[], tasks_v2.CloudTasksAsyncClient]


class AsyncCloudTasksClientProvider(AsyncClientProvider[tasks_v2.CloudTasksAsyncClient]):
    """
    Lazily resolves and caches a CloudTasksAsyncClient inside the running event loop.

    If ``auto_create_queue`` is True, the queue is ensured exactly once before the
    client is first handed out; a failed ensure is retried on the next call while
    the already-resolved client stays cached.

    Attributes
    ----------
        queue_path (str): The path to the Cloud Tasks queue.
        auto_create_queue (bool): Whether to ensure the queue exists on first use.

    """

    def __init__(
        self,
        *,
        client: tasks_v2.CloudTasksAsyncClient | AsyncCloudTasksClientFactory | None,
        queue_path: str,
        auto_create_queue: bool = False,
    ) -> None:
        super().__init__(client=client, client_cls=tasks_v2.CloudTasksAsyncClient)
        self.queue_path = queue_path
        self.auto_create_queue = auto_create_queue
        self._queue_ensured = not auto_create_queue
        self._ensure_lock = asyncio.Lock()

    async def get(self) -> tasks_v2.CloudTasksAsyncClient:
        """Return the cached client, ensuring the queue exists on first call if configured."""
        client = await super().get()
        if not self._queue_ensured:
            async with self._ensure_lock:
                if not self._queue_ensured:
                    await ensure_queue_async(client=client, path=self.queue_path)
                    self._queue_ensured = True
        return client


class AsyncDelayer(BaseDelayer):
    """
    A class to delay HTTP requests as tasks on Google Cloud Tasks, using an async client.

    See BaseDelayer for the shared attributes.

    Attributes
    ----------
        client_provider (AsyncCloudTasksClientProvider): Lazy provider for the async client.

    """

    def __init__(
        self,
        *,
        route: APIRoute,
        base_url: str,
        queue_path: str,
        client_provider: AsyncCloudTasksClientProvider,
        pre_create_hook: DelayedTaskHook,
        task_create_timeout: float = 10.0,
        countdown: int = 0,
        task_id: str | None = None,
    ) -> None:
        super().__init__(
            route=route,
            base_url=base_url,
            queue_path=queue_path,
            pre_create_hook=pre_create_hook,
            task_create_timeout=task_create_timeout,
            countdown=countdown,
            task_id=task_id,
        )
        self.client_provider = client_provider

    async def delay(self, **kwargs: Any) -> tasks_v2.Task:
        """Delay a task on Cloud Tasks without blocking the event loop."""
        client = await self.client_provider.get()
        request = self._build_create_task_request(values=kwargs)
        return await client.create_task(request=request, timeout=self.task_create_timeout)
