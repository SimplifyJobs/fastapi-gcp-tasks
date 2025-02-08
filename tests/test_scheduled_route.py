"""Tests for ScheduledRouteBuilder functionality."""

from fastapi import APIRouter
from google.protobuf import duration_pb2
from pydantic import BaseModel

from fastapi_gcp_tasks.hooks import deadline_scheduled_hook


class TestPayload(BaseModel):
    """Test payload for scheduled task endpoints."""

    message: str


def test_scheduled_task_creation(app, scheduled_route, test_client):
    """Test basic scheduled task creation."""
    router = APIRouter(route_class=scheduled_route)

    @router.post("/test-scheduled")
    async def test_task(payload: TestPayload):
        return {"received": payload.message}

    app.include_router(router)

    # Schedule a task
    test_task.scheduler(name="test-scheduled-task", schedule="*/5 * * * *", time_zone="UTC").schedule(
        payload=TestPayload(message="scheduled")
    )

    response = test_client.post("/test-scheduled", json={"message": "test"})
    assert response.status_code == 200


def test_scheduled_task_with_hook(app, scheduled_route, test_client):
    """Test scheduled task with deadline hook."""
    scheduled_route.pre_create_hook = deadline_scheduled_hook(duration=duration_pb2.Duration(seconds=300))
    router = APIRouter(route_class=scheduled_route)

    @router.post("/test-scheduled-hook")
    async def test_task(payload: TestPayload):
        return {"received": payload.message}

    app.include_router(router)

    # Schedule a task with hook
    test_task.scheduler(name="test-scheduled-task-hook", schedule="0 * * * *", time_zone="UTC").schedule(
        payload=TestPayload(message="scheduled with hook")
    )

    response = test_client.post("/test-scheduled-hook", json={"message": "test"})
    assert response.status_code == 200
