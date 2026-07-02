"""Smoke tests for the example app running against the Cloud Tasks emulator."""

import subprocess

import requests


def test_basic_task(uvicorn_server: subprocess.Popen[bytes], base_url: str) -> None:
    """Basic route should schedule a task and return a success message."""
    r = requests.get(f"{base_url}/basic", timeout=5)
    assert r.status_code == 200
    assert "scheduled" in r.json().get("message", "").lower()


def test_countdown_task(uvicorn_server: subprocess.Popen[bytes], base_url: str) -> None:
    """Countdown route should schedule a delayed task."""
    r = requests.get(f"{base_url}/with_countdown", timeout=5)
    assert r.status_code == 200


def test_async_basic_task(uvicorn_server: subprocess.Popen[bytes], base_url: str) -> None:
    """Async basic route should schedule a task via the async client and return a success message."""
    r = requests.get(f"{base_url}/async_basic", timeout=5)
    assert r.status_code == 200
    assert "scheduled" in r.json().get("message", "").lower()


def test_async_countdown_task(uvicorn_server: subprocess.Popen[bytes], base_url: str) -> None:
    """Async countdown route should schedule a delayed task via the async client."""
    r = requests.get(f"{base_url}/async_with_countdown", timeout=5)
    assert r.status_code == 200
