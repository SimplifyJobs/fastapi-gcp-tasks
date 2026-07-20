"""Regression tests for endpoints registered on more than one task path."""

# Standard Library Imports
from collections.abc import Callable
from unittest.mock import MagicMock

# Third Party Imports
import pytest
from fastapi import APIRouter
from fastapi.routing import APIRoute
from google.cloud import scheduler_v1, tasks_v2

# Imports from this repository
from fastapi_gcp_tasks import (
    AsyncDelayedRouteBuilder,
    AsyncScheduledRouteBuilder,
    DelayedRouteBuilder,
    ScheduledRouteBuilder,
)

QUEUE_PATH = "projects/test-project/locations/us-central1/queues/test-queue"
LOCATION_PATH = "projects/test-project/locations/us-central1"
CALLBACK_BASE_URL = "https://worker.example.com/tasks"

RouteClassFactory = Callable[[], type[APIRoute]]


def _delayed_route_class() -> type[APIRoute]:
    return DelayedRouteBuilder(
        callback_base_url=CALLBACK_BASE_URL,
        queue_path=QUEUE_PATH,
        client=MagicMock(spec=tasks_v2.CloudTasksClient),
        auto_create_queue=False,
    )


def _async_delayed_route_class() -> type[APIRoute]:
    return AsyncDelayedRouteBuilder(
        callback_base_url=CALLBACK_BASE_URL,
        queue_path=QUEUE_PATH,
        client=MagicMock(spec=tasks_v2.CloudTasksAsyncClient),
    )


def _scheduled_route_class() -> type[APIRoute]:
    return ScheduledRouteBuilder(
        callback_base_url=CALLBACK_BASE_URL,
        location_path=LOCATION_PATH,
        client=MagicMock(spec=scheduler_v1.CloudSchedulerClient),
    )


def _async_scheduled_route_class() -> type[APIRoute]:
    return AsyncScheduledRouteBuilder(
        callback_base_url=CALLBACK_BASE_URL,
        location_path=LOCATION_PATH,
        client=MagicMock(spec=scheduler_v1.CloudSchedulerAsyncClient),
    )


@pytest.mark.parametrize(
    "route_class_factory",
    [
        _delayed_route_class,
        _async_delayed_route_class,
        _scheduled_route_class,
        _async_scheduled_route_class,
    ],
)
def test_endpoint_cannot_be_registered_on_two_task_paths(route_class_factory: RouteClassFactory) -> None:
    """One function-level task helper cannot unambiguously represent two callback paths."""
    router = APIRouter(route_class=route_class_factory())

    def task() -> None:
        """Task endpoint."""

    router.add_api_route("/first", task, methods=["POST"])

    with pytest.raises(ValueError, match=r"already registered.*?/first.*?/second"):
        router.add_api_route("/second", task, methods=["POST"])


def test_endpoint_cannot_be_registered_by_two_delayed_route_builders() -> None:
    """Separate builder instances must not silently overwrite the same endpoint's helper."""
    first_router = APIRouter(route_class=_delayed_route_class())
    second_router = APIRouter(route_class=_delayed_route_class())

    def task() -> None:
        """Task endpoint."""

    first_router.add_api_route("/first", task, methods=["POST"])

    with pytest.raises(ValueError, match=r"already registered.*?/first.*?/second"):
        second_router.add_api_route("/second", task, methods=["POST"])
