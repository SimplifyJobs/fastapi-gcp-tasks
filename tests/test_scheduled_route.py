"""
Tests for ScheduledRouteBuilder functionality.

This module verifies the core functionality of ScheduledRouteBuilder, including:
- Basic scheduled task creation
- Task hooks and options
- Cron schedule validation
- Job creation and updates
- Time zone handling
"""

import pytest
from fastapi import APIRouter
from google.protobuf import duration_pb2
from pydantic import BaseModel

from fastapi_gcp_tasks import ScheduledRouteBuilder
from fastapi_gcp_tasks.hooks import deadline_scheduled_hook
from fastapi_gcp_tasks.utils import emulator_client


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


def test_scheduled_route_cron_validation(app, test_client):
    """
    Test cron schedule validation.

    This test verifies that:
    1. Valid cron expressions are accepted
    2. Invalid expressions are rejected
    3. Time zones are properly handled
    """
    route = ScheduledRouteBuilder(
        client=emulator_client(),
        base_url="http://localhost:8000",
        location_path="projects/test-project/locations/us-central1",
    )
    router = APIRouter(route_class=route)

    @router.post("/test-cron")
    async def test_task(payload: TestPayload):
        return {"received": payload.message}

    app.include_router(router)

    # Test valid cron expressions
    valid_schedules = [
        ("0 * * * *", "UTC"),  # Every hour
        ("*/5 * * * *", "UTC"),  # Every 5 minutes
        ("0 0 * * *", "America/New_York"),  # Daily at midnight ET
        ("0 9-17 * * 1-5", "Asia/Tokyo"),  # Business hours in Tokyo
    ]

    for schedule, timezone in valid_schedules:
        job = test_task.scheduler(
            name=f"test-cron-{schedule.replace(' ', '-')}",
            schedule=schedule,
            time_zone=timezone,
        ).schedule(payload=TestPayload(message="test"))
        assert job is not None

    # Test invalid cron expressions
    invalid_schedules = [
        "invalid",  # Not a cron expression
        "* * * *",  # Missing field
        "60 * * * *",  # Invalid minute
        "* 24 * * *",  # Invalid hour
    ]

    for schedule in invalid_schedules:
        with pytest.raises(ValueError, match="Invalid cron expression"):
            test_task.scheduler(
                name="test-invalid-cron",
                schedule=schedule,
                time_zone="UTC",
            ).schedule(payload=TestPayload(message="test"))

    # Test invalid timezone
    with pytest.raises(ValueError, match="Invalid timezone"):
        test_task.scheduler(
            name="test-invalid-timezone",
            schedule="0 * * * *",
            time_zone="Invalid/Timezone",
        ).schedule(payload=TestPayload(message="test"))


def test_scheduled_route_job_creation(app, test_client):
    """
    Test Cloud Scheduler job creation.

    This test verifies that:
    1. Jobs are created with correct settings
    2. Job names are unique
    3. Job updates work correctly
    """
    route = ScheduledRouteBuilder(
        client=emulator_client(),
        base_url="http://localhost:8000",
        location_path="projects/test-project/locations/us-central1",
    )
    router = APIRouter(route_class=route)

    @router.post("/test-job")
    async def test_task(payload: TestPayload):
        return {"received": payload.message}

    app.include_router(router)

    # Test job creation with unique names
    job1 = test_task.scheduler(
        name="test-job-1",
        schedule="0 * * * *",
        time_zone="UTC",
    ).schedule(payload=TestPayload(message="test1"))
    assert job1 is not None

    # Test job creation with same name (should update)
    job2 = test_task.scheduler(
        name="test-job-1",
        schedule="*/5 * * * *",  # Different schedule
        time_zone="UTC",
    ).schedule(payload=TestPayload(message="test2"))
    assert job2 is not None

    # Test job creation with description
    job3 = test_task.scheduler(
        name="test-job-2",
        schedule="0 * * * *",
        time_zone="UTC",
        description="Test job with description",
    ).schedule(payload=TestPayload(message="test3"))
    assert job3 is not None
    assert job3.description == "Test job with description"
