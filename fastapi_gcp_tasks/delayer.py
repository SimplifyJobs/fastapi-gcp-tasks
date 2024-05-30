# Standard Library Imports
import datetime
from typing import Any, Iterable

# Third Party Imports
from fastapi.routing import APIRoute
from google.cloud import tasks_v2
from google.protobuf import timestamp_pb2

# Imports from this repository
from fastapi_gcp_tasks.exception import BadMethodError
from fastapi_gcp_tasks.hooks import DelayedTaskHook
from fastapi_gcp_tasks.requester import Requester


class Delayer(Requester):
    """
    A class to delay HTTP requests as tasks on Google Cloud Tasks.

    Attributes
    ----------
        queue_path (str): The path to the Cloud Tasks queue.
        countdown (int): The delay in seconds before the task is executed.
        task_create_timeout (float): Timeout for creating the task.
        task_id (str): The unique identifier for the task.
        method (tasks_v2.HttpMethod): The HTTP method for the task.
        client (tasks_v2.CloudTasksClient): The Cloud Tasks client.
        pre_create_hook (DelayedTaskHook): Hook to be called before creating the task.

    """

    def __init__(
        self,
        *,
        route: APIRoute,
        base_url: str,
        queue_path: str,
        client: tasks_v2.CloudTasksClient,
        pre_create_hook: DelayedTaskHook,
        task_create_timeout: float = 10.0,
        countdown: int = 0,
        task_id: str | None = None,
    ) -> None:
        super().__init__(route=route, base_url=base_url)
        self.queue_path = queue_path
        self.countdown = countdown
        self.task_create_timeout = task_create_timeout

        self.task_id = task_id
        self.method = _task_method(route.methods)
        self.client = client
        self.pre_create_hook = pre_create_hook

    def delay(self, **kwargs: Any) -> tasks_v2.Task:
        """Delay a task on Cloud Tasks."""
        # Create http request
        request = tasks_v2.HttpRequest()
        request.http_method = self.method
        request.url = self._url(values=kwargs)
        request.headers = self._headers(values=kwargs)

        if body := self._body(values=kwargs):
            request.body = body

        # Scheduled the task
        task = tasks_v2.Task(http_request=request)
        if schedule_time := self._schedule():
            task.schedule_time = schedule_time

        # Make task name for deduplication
        if self.task_id:
            task.name = f"{self.queue_path}/tasks/{self.task_id}"

        request = tasks_v2.CreateTaskRequest(parent=self.queue_path, task=task)

        request = self.pre_create_hook(request)

        return self.client.create_task(request=request, timeout=self.task_create_timeout)

    def _schedule(self) -> timestamp_pb2.Timestamp | None:
        if self.countdown is None or self.countdown <= 0:
            return None
        d = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=self.countdown)
        timestamp = timestamp_pb2.Timestamp()
        timestamp.FromDatetime(d)
        return timestamp


def _task_method(methods: Iterable[str]) -> tasks_v2.HttpMethod:
    method_map = {
        "POST": tasks_v2.HttpMethod.POST,
        "GET": tasks_v2.HttpMethod.GET,
        "HEAD": tasks_v2.HttpMethod.HEAD,
        "PUT": tasks_v2.HttpMethod.PUT,
        "DELETE": tasks_v2.HttpMethod.DELETE,
        "PATCH": tasks_v2.HttpMethod.PATCH,
        "OPTIONS": tasks_v2.HttpMethod.OPTIONS,
    }
    methods = list(methods)
    # Only crash if we're being bound
    if len(methods) > 1:
        raise BadMethodError("Can't trigger task with multiple methods")
    method = method_map.get(methods[0])
    if method is None:
        raise BadMethodError(f"Unknown method {methods[0]}")
    return tasks_v2.HttpMethod(method)
