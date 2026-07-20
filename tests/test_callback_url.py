"""Tests for callback URL configuration and backward-compatible aliases."""

# Standard Library Imports
from typing import cast
from unittest.mock import MagicMock

# Third Party Imports
import pytest
from fastapi import APIRouter
from google.cloud import tasks_v2

# Imports from this repository
from fastapi_gcp_tasks import DelayedRouteBuilder, as_delayed_task
from fastapi_gcp_tasks._callback_url import resolve_callback_base_url
from fastapi_gcp_tasks.delayer import Delayer

QUEUE_PATH = "projects/test-project/locations/us-central1/queues/test-queue"


@pytest.mark.parametrize(
    ("callback_base_url", "base_url", "default", "expected"),
    [
        ("https://preferred.example", None, None, "https://preferred.example"),
        (None, "https://legacy.example", None, "https://legacy.example"),
        (None, None, "https://default.example", "https://default.example"),
    ],
)
def test_resolve_callback_base_url(
    callback_base_url: str | None,
    base_url: str | None,
    default: str | None,
    expected: str,
) -> None:
    """The preferred option, legacy alias, and builder default should resolve in order."""
    assert (
        resolve_callback_base_url(
            callback_base_url=callback_base_url,
            base_url=base_url,
            default=default,
        )
        == expected
    )


def test_resolve_callback_base_url_rejects_conflicting_names() -> None:
    """Passing both the preferred option and legacy alias should fail clearly."""
    with pytest.raises(TypeError, match="not both"):
        resolve_callback_base_url(
            callback_base_url="https://preferred.example",
            base_url="https://legacy.example",
        )


def test_resolve_callback_base_url_requires_a_value() -> None:
    """A builder without either callback URL spelling should fail clearly."""
    with pytest.raises(TypeError, match="callback_base_url"):
        resolve_callback_base_url(callback_base_url=None, base_url=None)


def test_delayed_task_accepts_per_call_callback_base_override() -> None:
    """A single delayed invocation should be able to target another callback base."""
    client = MagicMock(spec=tasks_v2.CloudTasksClient)
    route_class = DelayedRouteBuilder(
        callback_base_url="https://default.example/tasks",
        queue_path=QUEUE_PATH,
        client=client,
        auto_create_queue=False,
    )
    router = APIRouter(route_class=route_class)

    @router.post("/task")
    @as_delayed_task
    def task() -> None:
        """Task endpoint."""

    delayer = cast(Delayer, task.options(callback_base_url="https://override.example/tasks"))

    assert delayer.base_url == "https://override.example/tasks"


def test_delayed_task_rejects_conflicting_per_call_callback_names() -> None:
    """Per-call options should reject the preferred name combined with its alias."""
    client = MagicMock(spec=tasks_v2.CloudTasksClient)
    route_class = DelayedRouteBuilder(
        callback_base_url="https://default.example/tasks",
        queue_path=QUEUE_PATH,
        client=client,
        auto_create_queue=False,
    )
    router = APIRouter(route_class=route_class)

    @router.post("/task")
    @as_delayed_task
    def task() -> None:
        """Task endpoint."""

    with pytest.raises(TypeError, match="not both"):
        task.options(
            callback_base_url="https://preferred.example/tasks",
            base_url="https://legacy.example/tasks",
        )
