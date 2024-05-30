from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


def task_default_options(**kwargs: Any) -> Callable[[F], F]:
    """Wrapper to set default options for a cloud task."""

    def wrapper(fn: F) -> F:
        fn._delay_options = kwargs  # type: ignore[attr-defined]
        return fn

    return wrapper
