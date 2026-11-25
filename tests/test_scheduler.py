"""Unit tests for Scheduler using a mocked client."""

# Standard Library Imports
from typing import Any
from unittest.mock import MagicMock

# Third Party Imports
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from google.api_core.exceptions import AlreadyExists, NotFound, PermissionDenied
from google.cloud import scheduler_v1

# Imports from this repository
from fastapi_gcp_tasks.hooks import noop_hook
from fastapi_gcp_tasks.scheduler import Scheduler

LOCATION_PATH = "projects/test-project/locations/us-central1"
BASE_URL = "http://localhost"


def _make_route() -> APIRoute:
    app = FastAPI()

    @app.post("/scheduled_hello")
    def scheduled_hello() -> None:
        """Endpoint under test."""

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == "/scheduled_hello":
            return route
    raise ValueError("Route not found")


def _mock_client() -> MagicMock:
    client = MagicMock(spec=scheduler_v1.CloudSchedulerClient)
    client.get_job.side_effect = NotFound("no job")
    client.create_job.return_value = scheduler_v1.Job()
    return client


def _make_scheduler(client: Any, **kwargs: Any) -> Scheduler:
    return Scheduler(
        route=_make_route(),
        base_url=BASE_URL,
        location_path=LOCATION_PATH,
        schedule="*/5 * * * *",
        pre_create_hook=noop_hook,
        client=client,
        name="test-job",
        **kwargs,
    )


class TestSchedule:
    """Tests for the create-or-replace flow."""

    def test_creates_job_when_missing(self) -> None:
        """A missing job should be created."""
        client = _mock_client()

        _make_scheduler(client).schedule()

        client.create_job.assert_called_once()
        assert client.create_job.call_args.kwargs["request"].job.name == f"{LOCATION_PATH}/jobs/test-job"

    def test_first_time_scheduling_does_not_delete(self) -> None:
        """Creating a job that does not exist must work without permission to delete jobs."""
        client = _mock_client()
        client.delete_job.side_effect = PermissionDenied("nope")

        _make_scheduler(client).schedule()

        client.delete_job.assert_not_called()
        client.create_job.assert_called_once()

    def test_concurrent_create_of_the_same_job_is_not_an_error(self) -> None:
        """Two instances starting together: the one that loses the create race accepts the other's job."""
        client = _mock_client()
        scheduler = _make_scheduler(client)
        created_elsewhere = scheduler_v1.Job(scheduler._build_create_job_request(values={}).job)
        client.get_job.side_effect = [NotFound("no job"), created_elsewhere]
        client.create_job.side_effect = AlreadyExists("created by another instance")

        scheduler.schedule()

        client.create_job.assert_called_once()
        client.delete_job.assert_not_called()

    def test_concurrent_create_of_a_different_job_is_replaced(self) -> None:
        """If the job that won the race differs from ours, it is replaced like any changed job."""
        client = _mock_client()
        scheduler = _make_scheduler(client)
        client.get_job.side_effect = [
            NotFound("no job"),
            scheduler_v1.Job(name=scheduler.job_id, schedule="0 0 * * *"),
        ]
        client.create_job.side_effect = [AlreadyExists("created by another instance"), scheduler_v1.Job()]

        scheduler.schedule()

        client.delete_job.assert_called_once()
        assert client.create_job.call_count == 2

    def test_force_recreates_without_lookup(self) -> None:
        """force=True should skip the diff and always delete and recreate."""
        client = _mock_client()

        _make_scheduler(client, force=True).schedule()

        client.get_job.assert_not_called()
        client.delete_job.assert_called_once()
        client.create_job.assert_called_once()

    def test_skips_unchanged_job(self) -> None:
        """An identical existing job should not be recreated."""
        client = _mock_client()
        scheduler = _make_scheduler(client)
        existing = scheduler._build_create_job_request(values={}).job
        client.get_job.side_effect = None
        client.get_job.return_value = scheduler_v1.Job(existing)

        scheduler.schedule()

        client.delete_job.assert_not_called()
        client.create_job.assert_not_called()

    def test_recreates_changed_job(self) -> None:
        """A differing existing job should be deleted and recreated."""
        client = _mock_client()
        scheduler = _make_scheduler(client)
        client.get_job.side_effect = None
        client.get_job.return_value = scheduler_v1.Job(name=scheduler.job_id, schedule="0 0 * * *")

        scheduler.schedule()

        client.delete_job.assert_called_once()
        client.create_job.assert_called_once()

    def test_raises_when_existing_job_cannot_be_read(self) -> None:
        """A failed lookup is not "the job changed": do not delete and recreate on a guess."""
        client = _mock_client()
        client.get_job.side_effect = PermissionDenied("nope")

        with pytest.raises(PermissionDenied):
            _make_scheduler(client).schedule()

        client.delete_job.assert_not_called()
        client.create_job.assert_not_called()


class TestDelete:
    """Tests for delete(): a bool for the expected outcomes, an exception for everything else."""

    def test_returns_true_when_deleted(self) -> None:
        """delete() should return True when the job existed."""
        client = _mock_client()
        scheduler = _make_scheduler(client)

        assert scheduler.delete() is True
        client.delete_job.assert_called_once_with(name=scheduler.job_id, timeout=scheduler.job_create_timeout)

    def test_returns_false_when_job_is_missing(self) -> None:
        """delete() should return False, not an exception, when there is nothing to delete."""
        client = _mock_client()
        client.delete_job.side_effect = NotFound("no job")

        assert _make_scheduler(client).delete() is False

    def test_raises_unexpected_errors(self) -> None:
        """Anything other than "not found" is a real failure and must not be swallowed."""
        client = _mock_client()
        client.delete_job.side_effect = PermissionDenied("nope")

        with pytest.raises(PermissionDenied):
            _make_scheduler(client).delete()
