"""Shared fixtures for smoke tests."""

import os
import socket
import subprocess
import sys
import tempfile
import time
from typing import Generator

import pytest
import requests
from pydantic_settings import BaseSettings

TEST_PORT = 1738


class Settings(BaseSettings):
    """Test environment configuration."""

    is_local: bool = True
    task_project_id: str = "sample-project"
    task_location: str = "us-central1"
    scheduled_location: str = "us-central1"
    task_queue: str = "test-queue"
    cloud_tasks_emulator_url: str = "localhost:8123"


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Return parsed test settings."""
    return Settings()


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the test server."""
    return f"http://localhost:{TEST_PORT}"


def _wait_for_emulator(host: str, timeout_seconds: int = 30) -> None:
    """Wait for the Cloud Tasks emulator to accept TCP connections."""
    h, p = host.split(":")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            with socket.create_connection((h, int(p)), timeout=2):
                return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"Emulator not ready at {host}")


def _wait_for_service(url: str, proc: subprocess.Popen, log_file: str, timeout_seconds: int = 30) -> None:  # type: ignore[type-arg]
    """Wait for the uvicorn server to respond, aborting early if the process exits."""
    start = time.time()
    while time.time() - start < timeout_seconds:
        ret = proc.poll()
        if ret is not None:
            with open(log_file) as f:
                output = f.read()
            raise RuntimeError(f"uvicorn exited with code {ret}:\n{output}")
        try:
            r = requests.get(url, timeout=2)
            if r.status_code < 500:
                return
        except (requests.ConnectionError, requests.Timeout):
            pass
        time.sleep(0.5)
    with open(log_file) as f:
        output = f.read()
    raise TimeoutError(f"Service not ready at {url}:\n{output}")


@pytest.fixture(scope="session")
def uvicorn_server(settings: Settings, base_url: str) -> Generator[subprocess.Popen, None, None]:  # type: ignore[type-arg]
    """Start a uvicorn server for the example app and tear it down after tests."""
    _wait_for_emulator(settings.cloud_tasks_emulator_url)

    port = str(TEST_PORT)
    listener_url = f"{base_url}/_fastapi_cloud_tasks"

    env = os.environ.copy()
    env["IS_LOCAL"] = str(settings.is_local).lower()
    env["TASK_LISTENER_BASE_URL"] = listener_url
    env["TASK_PROJECT_ID"] = settings.task_project_id
    env["TASK_LOCATION"] = settings.task_location
    env["SCHEDULED_LOCATION"] = settings.scheduled_location
    env["TASK_QUEUE"] = settings.task_queue
    env["CLOUD_TASKS_EMULATOR_URL"] = settings.cloud_tasks_emulator_url

    # Write stdout to a temp file instead of a pipe to avoid deadlocking
    # the uvicorn process when the OS pipe buffer fills.
    log = tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "examples.full.main:app", "--host", "0.0.0.0", "--port", port],
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_service(f"{base_url}/docs", proc, log.name)
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()
        os.unlink(log.name)
