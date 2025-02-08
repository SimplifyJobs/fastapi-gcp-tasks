"""Tests for DelayedRouteBuilder functionality."""

from fastapi import APIRouter, Depends
from google.protobuf import duration_pb2
from pydantic import BaseModel

from fastapi_gcp_tasks.dependencies import max_retries
from fastapi_gcp_tasks.hooks import deadline_delayed_hook


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
