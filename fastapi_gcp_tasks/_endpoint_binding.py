"""Bind task helpers to endpoints without hiding ambiguous route registrations."""

# Standard Library Imports
from collections.abc import Callable, Mapping
from typing import Any

# Third Party Imports
from fastapi.routing import APIRoute


class _RouteInclusionMarker(dict[str, Any]):
    """
    Carry route identity through FastAPI's old inclusion clone path.

    FastAPI through 0.136 forwards the exact ``openapi_extra`` object when
    cloning a route. A dict subclass preserves every user-supplied OpenAPI
    value while keeping ``origin`` as Python-only metadata that is never
    emitted into the schema.
    """

    def __init__(self, *, origin: APIRoute, openapi_extra: dict[str, Any] | None) -> None:
        super().__init__(openapi_extra or {})
        self.origin = origin


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
        route.openapi_extra = _RouteInclusionMarker(
            origin=route,
            openapi_extra=route.openapi_extra,
        )
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
    marker = route.openapi_extra
    return (
        isinstance(existing_route, APIRoute)
        and type(existing_route) is type(route)
        and isinstance(marker, _RouteInclusionMarker)
        and marker.origin is existing_route
    )
