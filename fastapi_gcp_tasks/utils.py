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
    # We extract information from the queue path to make the public api simpler
    parsed_queue_path = client.parse_queue_path(path=path)
    create_req = tasks_v2.CreateQueueRequest(
        parent=location_path(**parsed_queue_path),
        queue=tasks_v2.Queue(name=path, **kwargs),
    )
    try:
        client.create_queue(request=create_req)
    except AlreadyExists:
        pass


def emulator_client(*, host: str = "localhost:8123") -> tasks_v2.CloudTasksClient:
    """Helper function to create a CloudTasksClient from an emulator host."""
    channel = grpc.insecure_channel(host)
    transport = transports.CloudTasksGrpcTransport(channel=channel)
    return tasks_v2.CloudTasksClient(transport=transport)
