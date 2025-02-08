import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fastapi_gcp_tasks import DelayedRouteBuilder, ScheduledRouteBuilder
from fastapi_gcp_tasks.utils import emulator_client, queue_path


@pytest.fixture
def app():
    """Create a fresh FastAPI application for each test."""
    return FastAPI()


@pytest.fixture
def delayed_route():
    """Create a DelayedRouteBuilder configured for testing with emulator."""
    return DelayedRouteBuilder(
        client=emulator_client(),
        base_url="http://localhost:8000",
        queue_path=queue_path(
            project="test-project",
            location="us-central1",
            queue="test-queue",
        ),
    )


@pytest.fixture
def scheduled_route():
    """Create a ScheduledRouteBuilder configured for testing."""
    return ScheduledRouteBuilder(
        base_url="http://localhost:8000",
        location_path="projects/test-project/locations/us-central1",
    )


@pytest.fixture
def test_client(app):
    """Create a TestClient instance for the FastAPI app."""
    return TestClient(app)
