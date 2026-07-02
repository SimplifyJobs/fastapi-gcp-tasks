# Standard Library Imports
from collections.abc import Callable
from typing import Any, TypeVar, Unpack

# Imports from this repository
from fastapi_gcp_tasks.protocols import DelayOptions, TaskDefaultOptions, ensure_known_options

F = TypeVar("F", bound=Callable[..., Any])


def task_default_options(**options: Unpack[TaskDefaultOptions]) -> Callable[[F], F]:
    """Wrapper to set default options for a cloud task."""
    # Runtime-validate against the superset (DelayOptions adds `client`): the
    # static type excludes `client` only because its type differs between the
    # sync and async builders, but the runtime supports it for both.
    ensure_known_options(options, DelayOptions)

    def wrapper(fn: F) -> F:
        # Stored on the function object; read back by the route builders when
        # constructing a delayer for this endpoint.
        fn._delay_options = options  # type: ignore[attr-defined]
        return fn

    return wrapper
