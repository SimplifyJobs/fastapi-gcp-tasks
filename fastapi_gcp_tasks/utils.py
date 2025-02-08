# Standard Library Imports
import os
from typing import Any

# Third Party Imports
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
    location_args = {k: v for k, v in parsed_queue_path.items() if k in ("project", "location")}
    create_req = tasks_v2.CreateQueueRequest(
        parent=location_path(**location_args),
        queue=tasks_v2.Queue(name=path, **kwargs),
    )
    try:
        client.create_queue(request=create_req)
    except AlreadyExists:
        pass


def emulator_client() -> tasks_v2.CloudTasksClient:
    """Helper function to create a CloudTasksClient from an emulator host."""
    host = os.getenv("CLOUD_TASKS_EMULATOR_HOST", "localhost")
    port = os.getenv("CLOUD_TASKS_EMULATOR_PORT", "8123")
    target = f"{host}:{port}"
    
    # Configure DNS resolution for Docker networking
    options = [
        ('grpc.enable_http_proxy', 0),
        ('grpc.enable_retries', 0),
        ('grpc.max_receive_message_length', -1),
        ('grpc.max_send_message_length', -1),
        ('grpc.keepalive_time_ms', 30000),
        ('grpc.dns_resolver_query_timeout_ms', 1000),
        ('grpc.dns_resolver_backoff_multiplier', 1.0),
        ('grpc.dns_resolver_backoff_jitter', 0.0),
        ('grpc.dns_resolver_backoff_min_seconds', 1),
        ('grpc.dns_resolver_backoff_max_seconds', 5),
    ]
    
    # Create channel with DNS resolution options
    channel = grpc.insecure_channel(target, options=options)
    transport = transports.CloudTasksGrpcTransport(channel=channel)
    return tasks_v2.CloudTasksClient(transport=transport)
