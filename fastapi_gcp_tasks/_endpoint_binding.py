"""Bind task helpers to endpoints without hiding ambiguous route registrations."""

# Standard Library Imports
from collections.abc import Callable, Mapping
from typing import Any

# Third Party Imports
from fastapi import __version__ as fastapi_version
from fastapi.routing import APIRoute

_FASTAPI_PRESERVES_ROUTER_TREES = tuple(int(part) for part in fastapi_version.split(".")[:2]) >= (0, 137)


def bind_endpoint_methods(
    route: APIRoute,
    *,
    primary_method_name: str,
    methods: Mapping[str, Callable[..., Any]],
) -> None:
    """Attach task methods once, allowing only old FastAPI inclusion clones to reuse them."""
    existing_method = getattr(route.endpoint, primary_method_name, None)
    if existing_method is None:
        for name, method in methods.items():
            setattr(route.endpoint, name, method)
        return

    existing_route = getattr(existing_method, "__self__", None)
    if _is_inclusion_clone(existing_route=existing_route, route=route):
        return

    endpoint_name = getattr(route.endpoint, "__name__", repr(route.endpoint))
    existing_path = getattr(existing_route, "path", "an unknown path")
    raise ValueError(
        f"Endpoint {endpoint_name!r} is already registered as a task at {existing_path!r}; "
        f"it cannot also be registered at {route.path!r} because its function-level "
        f".{primary_method_name} helper can represent only one callback path."
    )


def _is_inclusion_clone(*, existing_route: object, route: APIRoute) -> bool:
    """Return whether ``route`` is a copy made by FastAPI's old ``include_router`` implementation."""
    if not isinstance(existing_route, APIRoute) or type(existing_route) is not type(route):
        return False
    if route.path == existing_route.path:
        return True
    return not _FASTAPI_PRESERVES_ROUTER_TREES and route.path.endswith(existing_route.path)
