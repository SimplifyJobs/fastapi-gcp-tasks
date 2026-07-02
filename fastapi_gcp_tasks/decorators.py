# Standard Library Imports
from collections.abc import Callable
from typing import Any, TypeVar, Unpack, overload

# Imports from this repository
from fastapi_gcp_tasks.protocols import AsyncDelayOptions, DelayOptions, ensure_known_options

F = TypeVar("F", bound=Callable[..., Any])

# Overloaded so that `client` stays statically usable with either builder:
# a CloudTasksClient matches the DelayOptions overload, a CloudTasksAsyncClient
# (or factory) matches the AsyncDelayOptions one. All other keys are shared.


@overload
def task_default_options(**options: Unpack[DelayOptions]) -> Callable[[F], F]: ...


@overload
def task_default_options(**options: Unpack[AsyncDelayOptions]) -> Callable[[F], F]: ...


def task_default_options(**options: Any) -> Callable[[F], F]:
    """Wrapper to set default options for a cloud task."""
    ensure_known_options(options, DelayOptions)

    def wrapper(fn: F) -> F:
        # Stored on the function object; read back by the route builders when
        # constructing a delayer for this endpoint.
        fn._delay_options = options  # type: ignore[attr-defined]
        return fn

    return wrapper
