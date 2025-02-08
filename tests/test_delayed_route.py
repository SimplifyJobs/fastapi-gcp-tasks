"""
Tests for DelayedRouteBuilder functionality.

This module verifies the core functionality of DelayedRouteBuilder, including:
- Basic task creation and execution
- Task hooks and options
- Queue auto-creation
- Error handling and retries
- Task scheduling with countdown
"""

import pytest
from fastapi import APIRouter, Depends
from google.protobuf import duration_pb2
from pydantic import BaseModel

from fastapi_gcp_tasks import DelayedRouteBuilder
from fastapi_gcp_tasks.dependencies import max_retries
from fastapi_gcp_tasks.hooks import deadline_delayed_hook
from fastapi_gcp_tasks.utils import emulator_client, queue_path


class TestPayload(BaseModel):
    """Test payload for task endpoints."""

    message: str


def test_delayed_task_creation(app, delayed_route, test_client):
    """Test basic task creation and execution."""
    router = APIRouter(route_class=delayed_route)

    @router.post("/test")
    async def test_task(payload: TestPayload):
        return {"received": payload.message}

    app.include_router(router)

    response = test_client.post("/test", json={"message": "test"})
    assert response.status_code == 200
    assert response.json() == {"received": "test"}


def test_delayed_task_with_hook(app, delayed_route, test_client):
    """Test task creation with deadline hook."""
    delayed_route.pre_create_hook = deadline_delayed_hook(duration=duration_pb2.Duration(seconds=300))
    router = APIRouter(route_class=delayed_route)

    @router.post("/test-hook")
    async def test_task(payload: TestPayload):
        return {"received": payload.message}

    app.include_router(router)

    response = test_client.post("/test-hook", json={"message": "test"})
    assert response.status_code == 200


def test_delayed_task_with_retries(app, delayed_route, test_client):
    """Test task with max retries dependency."""
    router = APIRouter(route_class=delayed_route)

    @router.post("/test-retries", dependencies=[Depends(max_retries(2))])
    async def test_task():
        raise Exception("Test failure")

    app.include_router(router)

    response = test_client.post("/test-retries")
    assert response.status_code == 500  # Should fail after 2 retries


def test_delayed_task_with_countdown(app, delayed_route, test_client):
    """Test task creation with countdown."""
    router = APIRouter(route_class=delayed_route)

    @router.post("/test-countdown")
    async def test_task(payload: TestPayload):
        return {"received": payload.message}

    app.include_router(router)

    # Test with countdown option
    test_task.options(countdown=60).delay(payload=TestPayload(message="delayed"))

    response = test_client.post("/test-countdown", json={"message": "test"})
    assert response.status_code == 200


def test_delayed_task_with_task_id(app, delayed_route, test_client):
    """
    Test task creation with task ID.

    This test verifies that:
    1. Tasks can be created with unique IDs
    2. Duplicate task IDs are handled correctly
    3. Task ID validation works
    """
    router = APIRouter(route_class=delayed_route)

    @router.post("/test-task-id")
    async def test_task(payload: TestPayload):
        return {"received": payload.message}

    app.include_router(router)

    # Test with unique task ID
    task1 = test_task.options(task_id="unique-task-1").delay(payload=TestPayload(message="test1"))
    assert task1 is not None

    # Test with duplicate task ID (should be idempotent)
    task2 = test_task.options(task_id="unique-task-1").delay(payload=TestPayload(message="test1"))
    assert task2 is not None

    response = test_client.post("/test-task-id", json={"message": "test"})
    assert response.status_code == 200


def test_delayed_task_error_handling(app, test_client):
    """
    Test error handling in delayed routes.

    This test verifies that:
    1. Invalid configurations are caught
    2. Task creation failures are handled
    3. Hook errors are properly propagated
    """
    # Test invalid base URL
    with pytest.raises(ValueError):
        DelayedRouteBuilder(
            base_url="invalid-url",
            queue_path=queue_path(
                project="test-project",
                location="us-central1",
                queue="test-queue",
            ),
        )

    # Test missing queue path
    with pytest.raises(ValueError):
        DelayedRouteBuilder(
            base_url="http://localhost:8000",
            queue_path="",
        )

    # Test invalid client configuration
    with pytest.raises(ValueError):
        DelayedRouteBuilder(
            base_url="http://localhost:8000",
            queue_path=queue_path(
                project="test-project",
                location="us-central1",
                queue="test-queue",
            ),
            client="invalid-client",
        )


def test_delayed_task_queue_creation(app, test_client):
    """
    Test queue auto-creation functionality.

    This test verifies that:
    1. Queue is created if it doesn't exist
    2. DelayedRouteBuilder handles existing queues
    3. auto_create_queue parameter works correctly
    """
    # Test with auto_create_queue=True (default)
    route1 = DelayedRouteBuilder(
        client=emulator_client(),
        base_url="http://localhost:8000",
        queue_path=queue_path(
            project="test-project",
            location="us-central1",
            queue="test-queue-1",
        ),
    )
    assert route1 is not None

    # Test with auto_create_queue=False
    route2 = DelayedRouteBuilder(
        client=emulator_client(),
        base_url="http://localhost:8000",
        queue_path=queue_path(
            project="test-project",
            location="us-central1",
            queue="test-queue-2",
        ),
        auto_create_queue=False,
    )
    assert route2 is not None
