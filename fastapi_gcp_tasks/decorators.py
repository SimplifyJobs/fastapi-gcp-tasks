# Standard Library Imports
from collections.abc import Callable
from typing import Any, TypeVar, Unpack

# Imports from this repository
from fastapi_gcp_tasks.protocols import TaskDefaultOptions

F = TypeVar("F", bound=Callable[..., Any])


def task_default_options(**options: Unpack[TaskDefaultOptions]) -> Callable[[F], F]:
    """Wrapper to set default options for a cloud task."""

    def wrapper(fn: F) -> F:
        # Stored on the function object; read back by the route builders when
        # constructing a delayer for this endpoint.
        fn._delay_options = options  # type: ignore[attr-defined]
        return fn

    return wrapper
