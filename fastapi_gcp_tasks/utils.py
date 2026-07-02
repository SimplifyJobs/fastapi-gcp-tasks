# Third Party Imports
from typing import Any

import grpc
from google.api_core.exceptions import AlreadyExists
from google.cloud import scheduler_v1, tasks_v2
from google.cloud.tasks_v2.services.cloud_tasks import transports


def location_path(*, project: str, location: str) -> str:
    """Helper function to construct a location path for Cloud Scheduler."""
    return scheduler_v1.CloudSchedulerClient.common_location_path(project=project, location=location)


def queue_path(*, project: str, location: str, queue: str) -> str:
    """Helper function to construct a queue path for Cloud Tasks."""
    return tasks_v2.CloudTasksClient.queue_path(project=project, location=location, queue=queue)


def _create_queue_request(*, path: str, **kwargs: Any) -> tasks_v2.CreateQueueRequest:
    # We extract information from the queue path to make the public api simpler
    parsed_queue_path = tasks_v2.CloudTasksClient.parse_queue_path(path=path)
    return tasks_v2.CreateQueueRequest(
        parent=location_path(project=parsed_queue_path["project"], location=parsed_queue_path["location"]),
        queue=tasks_v2.Queue(name=path, **kwargs),
    )


def ensure_queue(
    *,
    client: tasks_v2.CloudTasksClient,
    path: str,
    **kwargs: Any,
) -> None:
    """
    Helper function to ensure a Cloud Tasks queue exists.

    If the queue already exists, this function will not raise an error.
    If the queue does not exist, it will be created with the provided kwargs.
    """
    try:
        client.create_queue(request=_create_queue_request(path=path, **kwargs))
    except AlreadyExists:
        pass


async def ensure_queue_async(
    *,
    client: tasks_v2.CloudTasksAsyncClient,
    path: str,
    **kwargs: Any,
) -> None:
    """
    Helper function to ensure a Cloud Tasks queue exists, using an async client.

    If the queue already exists, this function will not raise an error.
    If the queue does not exist, it will be created with the provided kwargs.

    Recommended usage is to call this once from your FastAPI lifespan.
    """
    try:
        await client.create_queue(request=_create_queue_request(path=path, **kwargs))
    except AlreadyExists:
        pass


def emulator_client(*, host: str = "localhost:8123") -> tasks_v2.CloudTasksClient:
    """Helper function to create a CloudTasksClient from an emulator host."""
    channel = grpc.insecure_channel(host)
    transport = transports.CloudTasksGrpcTransport(channel=channel)
    return tasks_v2.CloudTasksClient(transport=transport)


def async_emulator_client(*, host: str = "localhost:8123") -> tasks_v2.CloudTasksAsyncClient:
    """
    Helper function to create a CloudTasksAsyncClient from an emulator host.

    Note: grpc.aio channels bind to the event loop active at construction, so call
    this inside a running event loop, or pass it as a client factory to
    AsyncDelayedRouteBuilder (e.g. ``client=lambda: async_emulator_client(host=...)``).
    """
    channel = grpc.aio.insecure_channel(host)
    transport = transports.CloudTasksGrpcAsyncIOTransport(channel=channel)
    return tasks_v2.CloudTasksAsyncClient(transport=transport)
