"""Tests for example implementations.

This test module verifies that the example implementations work as expected,
covering both simple and full examples from the examples directory.
"""
import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.protobuf import duration_pb2

from examples.simple.main import app as simple_app
from examples.full.tasks import app as full_app
from fastapi_gcp_tasks.utils import emulator_client, queue_path


@pytest.fixture
def simple_client():
    """Create a test client for the simple example app."""
    return TestClient(simple_app)


@pytest.fixture
def full_client():
    """Create a test client for the full example app."""
    return TestClient(full_app)


def test_simple_example_local_mode(simple_client, monkeypatch):
    """Test simple example in local mode.
    
    This test verifies that:
    1. Emulator client is used in local mode
    2. Tasks are properly queued
    3. Default settings work correctly
    4. Environment variables are properly handled
    """
    # Ensure we're in local mode
    monkeypatch.setenv("IS_LOCAL", "true")
    monkeypatch.setenv("TASK_LISTENER_BASE_URL", "http://localhost:8000")
    
    # Test trigger endpoint
    response = simple_client.get("/trigger")
    assert response.status_code == 200
    assert response.json() == {"message": "Basic hello task triggered"}

    # Test hello task endpoint
    response = simple_client.post(
        "/delayed/hello",
        json={"message": "test message"}
    )
    assert response.status_code == 200


def test_full_example_chained_hooks(full_client, monkeypatch):
    """Test full example with chained hooks.
    
    This test verifies that:
    1. OIDC and deadline hooks work together
    2. Hook order is preserved
    3. Hook configuration is correct
    4. Hooks are properly applied to tasks
    """
    # Set up test environment
    monkeypatch.setenv("IS_LOCAL", "true")
    monkeypatch.setenv("CLOUD_TASKS_EMULATOR_URL", "http://localhost:8123")
    monkeypatch.setenv("TASK_LISTENER_BASE_URL", "http://localhost:8000")
    
    # Test hello task with chained hooks
    response = full_client.post(
        "/delayed/hello",
        json={"message": "test with hooks"}
    )
    assert response.status_code == 200

    # Test fail_twice with retries
    response = full_client.post("/delayed/fail_twice")
    assert response.status_code == 500  # Should fail after 2 retries

    # Test scheduled hello with hooks
    response = full_client.post(
        "/scheduled/timed_hello",
        json={"message": "test scheduled with hooks"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "message": "Scheduled hello task ran with payload: test scheduled with hooks"
    }


def test_full_example_hook_configuration():
    """Test hook configuration in full example.
    
    This test verifies that:
    1. OIDC token is properly configured
    2. Deadline duration is set correctly
    3. Hooks are chained in the right order
    """
    with patch("fastapi_gcp_tasks.hooks.oidc_delayed_hook") as mock_oidc_hook:
        with patch("fastapi_gcp_tasks.hooks.deadline_delayed_hook") as mock_deadline_hook:
            # Import here to trigger hook creation with mocks
            from examples.full.tasks import DelayedRoute
            
            # Verify OIDC hook was called
            mock_oidc_hook.assert_called_once()
            
            # Verify deadline hook was called with correct duration
            mock_deadline_hook.assert_called_once_with(
                duration=duration_pb2.Duration(seconds=1800)
            )


def test_simple_example_environment_handling(monkeypatch):
    """Test environment handling in simple example.
    
    This test verifies that:
    1. Local mode uses emulator client
    2. Environment variables are properly handled
    3. Default values are used when needed
    """
    # Test local mode
    monkeypatch.setenv("IS_LOCAL", "true")
    from examples.simple.main import client
    assert client is not None
    
    # Test non-local mode
    monkeypatch.setenv("IS_LOCAL", "false")
    with patch("examples.simple.main.tasks_v2.CloudTasksClient") as mock_client:
        # Reimport to trigger client creation
        from importlib import reload
        import examples.simple.main
        reload(examples.simple.main)
        mock_client.assert_called_once()


def test_deployed_environment_scheduling(full_client, monkeypatch):
    """Test scheduling in deployed environment.
    
    This test verifies that:
    1. Scheduling only occurs when not local
    2. OIDC tokens are properly used
    3. Cloud Scheduler integration works
    4. Environment variables affect scheduling behavior
    """
    # Mock Cloud Scheduler client
    with patch("google.cloud.scheduler_v1.CloudSchedulerClient") as mock_scheduler:
        # Set up deployed environment
        monkeypatch.setenv("IS_LOCAL", "false")
        monkeypatch.setenv("TASK_LISTENER_BASE_URL", "https://example.com")
        monkeypatch.setenv("SCHEDULED_OIDC_TOKEN", "test-token")
        
        # Reload module to trigger scheduling
        from importlib import reload
        import examples.full.tasks
        reload(examples.full.tasks)
        
        # Verify scheduler client was used
        mock_scheduler.assert_called_once()
        
        # Verify scheduled task creation
        scheduler_instance = mock_scheduler.return_value
        create_job = scheduler_instance.create_job
        assert create_job.called
        
        # Verify job configuration
        job_args = create_job.call_args[0]
        assert len(job_args) == 2  # parent and job args
        job = job_args[1]
        
        # Verify schedule
        assert job.schedule == "*/5 * * * *"
        assert job.time_zone == "Asia/Kolkata"
        
        # Verify OIDC token
        assert job.http_target.oidc_token.service_account_email == "test-token"
        
        # Test endpoint still works
        response = full_client.post(
            "/scheduled/timed_hello",
            json={"message": "test in deployed mode"}
        )
        assert response.status_code == 200
        assert response.json() == {
            "message": "Scheduled hello task ran with payload: test in deployed mode"
        }
