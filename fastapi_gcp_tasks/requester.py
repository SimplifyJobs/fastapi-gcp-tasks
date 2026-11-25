# Standard Library Imports
import inspect
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from http.cookies import SimpleCookie
from types import UnionType
from typing import Any, Union, get_args, get_origin
from urllib.parse import ParseResult, parse_qsl, quote, urlencode, urlparse, urlunparse

# Third Party Imports
from fastapi import params
from fastapi.dependencies.models import Dependant
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.convertors import PathConvertor

# Imports from this repository
from fastapi_gcp_tasks.exception import MissingParamError, WrongTypeError

try:
    # Third Party Imports
    import ujson as json
except ImportError:
    # Standard Library Imports
    import json  # type: ignore[no-redef]

# Headers that Cloud Tasks / Cloud Scheduler set themselves on every dispatch.
# Endpoints may declare them to read them, but we must never send them.
_RESERVED_HEADER_PREFIXES = ("x-cloudtasks-", "x-cloudscheduler")

_COLLECTIONS = (list, tuple, set, frozenset)
_MISSING: Any = object()
_COOKIES = SimpleCookie()


@dataclass(frozen=True)
class _Param:
    """One query, header, cookie or body parameter a task accepts."""

    # Keyword the caller uses: the Python parameter name.
    name: str
    # Name on the wire, as FastAPI resolved it (alias, or the dashed name of a header).
    wire: str
    # FastAPI's ModelField for the parameter (private type, so untyped here).
    field: Any
    # Declared on the endpoint itself. Required-ness and defaults only apply to
    # these; parameters owned by dependencies are forwarded when passed but never
    # required, because hooks or Cloud Tasks itself often supply them (e.g. the
    # Authorization header an OIDC-verifying dependency reads).
    own: bool
    # A Pydantic model grouping several parameters (FastAPI "parameter models").
    is_model: bool = False
    # Body params only: None is a value this parameter accepts, so an explicit None
    # is sent as JSON null instead of being read as "not provided".
    nullable: bool = False


@dataclass(frozen=True)
class _PathParam:
    """One path parameter in the route's path template."""

    name: str
    key: str
    field: Any | None
    keep_slashes: bool


@dataclass(frozen=True)
class _RoutePlan:
    """Everything needed to turn call arguments into an HTTP request for one route, computed once."""

    endpoint_name: str
    path: tuple[_PathParam, ...]
    query: tuple[_Param, ...]
    headers: tuple[_Param, ...]
    cookies: tuple[_Param, ...]
    body: tuple[_Param, ...]
    embed_body: bool
    form_body: bool
    positional: tuple[str, ...]
    accepted: frozenset[str]
    injected: frozenset[str]


# Routes are not hashable (Starlette defines __eq__), so the plan is cached on the route instance itself.
_PLAN_ATTR = "_fastapi_gcp_tasks_plan"


class Requester:
    """
    A class to construct HTTP requests based on FastAPI routes, handling headers, URL construction, and request bodies.

    Attributes
    ----------
        route (APIRoute): The FastAPI route object.
        base_url (str): The base URL for the requests.

    """

    def __init__(
        self,
        *,
        route: APIRoute,
        base_url: str,
    ) -> None:
        self.route = route
        self.base_url = base_url.rstrip("/")
        self._plan = _plan_for(route)

    def _bind(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
        """Map call arguments onto the endpoint's parameter names, like a normal call would."""
        plan = self._plan
        if not args and plan.accepted.issuperset(kwargs):
            return kwargs

        if len(args) > len(plan.positional):
            raise TypeError(
                f"{plan.endpoint_name}() takes {len(plan.positional)} positional argument(s) but {len(args)} were given"
            )
        values = dict(kwargs)
        for name, arg in zip(plan.positional, args, strict=False):
            if name in values:
                raise TypeError(f"{plan.endpoint_name}() got multiple values for argument {name!r}")
            values[name] = arg

        unexpected = [name for name in values if name not in plan.accepted]
        if unexpected:
            injected = sorted(name for name in unexpected if name in plan.injected)
            if injected:
                raise TypeError(
                    f"{plan.endpoint_name}() cannot take {', '.join(map(repr, injected))} when triggered as a task: "
                    "the worker resolves it itself (a dependency or a FastAPI-injected object), "
                    "so a value passed here would be dropped"
                )
            raise TypeError(
                f"{plan.endpoint_name}() got unexpected keyword argument(s): {', '.join(map(repr, sorted(unexpected)))}"
            )
        return values

    def _headers(self, *, values: dict[str, Any]) -> dict[str, str]:
        plan = self._plan
        headers: dict[str, str] = {}
        for param in plan.headers:
            value = _resolve(param, values, location="header")
            if value is None:
                continue
            pairs = _expand_model(param, value, header=True) if param.is_model else [(param.wire, value)]
            for key, item in pairs:
                header_value = _header_value(key, item)
                if header_value is not None:
                    headers[key] = header_value

        cookies: list[str] = []
        for param in plan.cookies:
            value = _resolve(param, values, location="cookie")
            if value is None:
                continue
            pairs = _expand_model(param, value) if param.is_model else [(param.wire, value)]
            # Quote like the stdlib does, so a ";" or "," in a value cannot end it early
            cookies.extend(f"{key}={_COOKIES.value_encode(_to_wire(item))[1]}" for key, item in pairs)
        if cookies:
            headers["Cookie"] = "; ".join(cookies)

        # We use json only.
        headers["Content-Type"] = "application/json"
        return headers

    def _url(self, *, values: dict[str, Any]) -> str:
        plan = self._plan
        path = self.route.path_format
        for path_param in plan.path:
            value = values.get(path_param.name)
            if value is None:
                raise MissingParamError(param=path_param.name)
            if path_param.field is not None:
                value = _validate(path_param.field, value, loc=("path", path_param.key))
            segment = _to_wire(value)
            if not segment or ("/" in segment and not path_param.keep_slashes):
                # ASGI servers decode %2F before routing, so such a value could never
                # reach this route (Starlette's own url_path_for rejects it too).
                raise ValueError(
                    f"path parameter {path_param.name!r} must be non-empty and must not contain '/' "
                    f"(got {segment!r}); declare it as '{{{path_param.key}:path}}' to allow slashes"
                )
            # Percent-encode so reserved characters stay inside the segment instead
            # of being read as a query string or a fragment.
            encoded = quote(segment, safe="/" if path_param.keep_slashes else "")
            path = path.replace("{" + path_param.key + "}", encoded)

        query: list[tuple[str, str]] = []
        set_keys: set[str] = set()
        for param in plan.query:
            value = _resolve(param, values, location="query")
            if value is None:
                continue
            pairs = _expand_model(param, value) if param.is_model else [(param.wire, value)]
            for key, item in pairs:
                set_keys.add(key)
                if isinstance(item, _COLLECTIONS):
                    elements = [_to_wire(element) for element in item]
                    if isinstance(item, (set, frozenset)):
                        # Sets have no stable order; sort so the same call always builds the same URL
                        elements.sort()
                    query.extend((key, element) for element in elements)
                else:
                    query.append((key, _to_wire(item)))

        # Note: you might think urljoin is a better solution here, it is not.
        base = _parse_base_url(self.base_url)
        full_path = base.path.strip("/") + "/" + path.strip("/")
        if base.query:
            # Keep query params from the base url unless the task sets the same key
            query = [pair for pair in parse_qsl(base.query) if pair[0] not in set_keys] + query
        return urlunparse(base._replace(path=full_path, query=urlencode(query)))

    def _body(self, *, values: dict[str, Any]) -> bytes | None:
        plan = self._plan
        if not plan.body:
            return None
        if plan.form_body:
            raise TypeError(
                f"{plan.endpoint_name}() declares Form/File parameters, which cannot be triggered as a task: "
                "task bodies are always sent as JSON"
            )
        if not plan.embed_body:
            return _dump_json(_body_value(plan.body[0], values))

        # Several body params (or Body(embed=True)): FastAPI expects one JSON object
        # keyed by parameter name.
        members: list[bytes] = []
        for param in plan.body:
            value = _body_value(param, values)
            if value is None and not _is_explicit_null(param, values):
                # Not provided and no default to send: leave it to the worker
                continue
            members.append(json.dumps(param.wire).encode() + b": " + _dump_json(value))
        return b"{" + b", ".join(members) + b"}"


def _plan_for(route: APIRoute) -> _RoutePlan:
    plan: _RoutePlan | None = route.__dict__.get(_PLAN_ATTR)
    if plan is None:
        plan = _build_plan(route)
        route.__dict__[_PLAN_ATTR] = plan
    return plan


def _build_plan(route: APIRoute) -> _RoutePlan:
    root = route.dependant
    # The endpoint's own params first, so they win over a dependency declaring the same name
    dependants = [(True, root), *((False, dependant) for dependant in _sub_dependants(root))]

    def collect(attr: str, *, group: bool = True) -> tuple[_Param, ...]:
        found: dict[str, _Param] = {}
        for own, dependant in dependants:
            for field in getattr(dependant, attr):
                wire = _wire_name(field)
                if wire not in found:
                    found[wire] = _Param(
                        name=field.name,
                        wire=wire,
                        field=field,
                        own=own,
                        is_model=group and _is_param_model(field),
                    )
        return tuple(found.values())

    query = collect("query_params")
    all_headers = collect("header_params")
    cookies = collect("cookie_params")
    # The JSON body is one document that only the caller can supply, so every body param
    # is treated as the endpoint's own, even when a dependency declares it
    body = tuple(
        _Param(name=p.name, wire=p.wire, field=p.field, own=True, nullable=_accepts_none(p.field))
        for p in collect("body_params", group=False)
    )
    path_fields = collect("path_params", group=False)

    path = tuple(_path_param(key, convertor, path_fields) for key, convertor in route.param_convertors.items())

    accepted = frozenset(
        [param.name for param in (*query, *all_headers, *cookies, *body)] + [param.name for param in path]
    )
    positional: tuple[str, ...] = ()
    injected: frozenset[str] = frozenset()
    try:
        signature = inspect.signature(route.endpoint)
    except (TypeError, ValueError):  # pragma: no cover - endpoints without an introspectable signature
        pass
    else:
        positional = tuple(
            name
            for name, parameter in signature.parameters.items()
            if parameter.kind in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
        )
        injected = frozenset(signature.parameters) - accepted

    return _RoutePlan(
        endpoint_name=getattr(route.endpoint, "__name__", "task"),
        path=path,
        query=query,
        headers=tuple(p for p in all_headers if not p.wire.lower().startswith(_RESERVED_HEADER_PREFIXES)),
        cookies=cookies,
        body=body,
        # A lone, non-embedded body param is used by FastAPI as the body field itself;
        # anything else is wrapped in a synthetic model keyed by parameter name.
        embed_body=bool(body) and not any(route.body_field is param.field for param in body),
        form_body=any(isinstance(param.field.field_info, params.Form) for param in body),
        positional=positional,
        accepted=accepted,
        injected=injected,
    )


def _sub_dependants(dependant: Dependant) -> Iterator[Dependant]:
    for sub_dependant in dependant.dependencies:
        yield sub_dependant
        yield from _sub_dependants(sub_dependant)


def _path_param(key: str, convertor: Any, declared: tuple[_Param, ...]) -> _PathParam:
    # A path segment may have no declared parameter at all; it is then passed by its template name
    match = next((param for param in declared if param.wire == key or param.name == key), None)
    return _PathParam(
        name=match.name if match is not None else key,
        key=key,
        field=match.field if match is not None else None,
        keep_slashes=isinstance(convertor, PathConvertor),
    )


def _wire_name(field: Any) -> str:
    # FastAPI has already resolved the name it will read: for a header that is the dashed
    # name unless convert_underscores is off or an explicit alias was given. Use it as is.
    validation_alias = getattr(field.field_info, "validation_alias", None)
    wire: str = validation_alias if isinstance(validation_alias, str) and validation_alias else field.alias
    return wire


def _is_param_model(field: Any) -> bool:
    annotation = field.field_info.annotation
    if get_origin(annotation) in (Union, UnionType):
        # An optional parameter model: `Filters | None`
        members = [member for member in get_args(annotation) if member is not type(None)]
        if len(members) != 1:
            return False
        annotation = members[0]
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _accepts_none(field: Any) -> bool:
    _, errors = field.validate(None, {}, loc=("body",))
    return not errors


def _expand_model(param: _Param, value: Any, *, header: bool = False) -> list[tuple[str, Any]]:
    """Flatten a parameter model into its individual (wire name, value) params."""
    convert_underscores = header and getattr(param.field.field_info, "convert_underscores", True)
    pairs: list[tuple[str, Any]] = []
    for name, info in type(value).model_fields.items():
        item = getattr(value, name)
        if item is None:
            continue
        validation_alias = info.validation_alias
        key = validation_alias if isinstance(validation_alias, str) and validation_alias else (info.alias or name)
        if convert_underscores and key == name:
            key = key.replace("_", "-")
        pairs.append((key, item))
    return pairs


def _resolve(param: _Param, values: dict[str, Any], *, location: str) -> Any:
    """Return the validated value to send for a param, or None when nothing should be sent."""
    value = values.get(param.name)
    if value is None:
        if not param.own:
            return None
        if param.field.field_info.is_required():
            raise MissingParamError(param=param.name)
        # None is "not provided" for every non-body location: never send the text "None"
        return param.field.get_default()
    value = _validate(param.field, value, loc=(location, param.wire))
    if isinstance(value, _COLLECTIONS) and not value:
        # An empty collection has no representation in a URL or header: the key is simply
        # absent, so the worker would use its own default. Only allow it when that is the same.
        required = param.field.field_info.is_required()
        default = None if required else param.field.get_default()
        if not isinstance(default, _COLLECTIONS) or default:
            outcome = "reject the request" if required else f"use its default ({default!r})"
            raise ValueError(
                f"{location} parameter {param.name!r} cannot be sent as an empty collection: "
                f"the worker would {outcome} instead"
            )
    return value


def _validate(field: Any, value: Any, *, loc: tuple[str, ...]) -> Any:
    validated, errors = field.validate(value, {}, loc=loc)
    if errors:
        # TODO: Log everything but raise first only
        # TODO: find a better way to raise and display these errors
        raise ValueError(str(errors[0]))
    return validated


def _is_explicit_null(param: _Param, values: dict[str, Any]) -> bool:
    return param.nullable and values.get(param.name, _MISSING) is None


def _body_value(param: _Param, values: dict[str, Any]) -> Any:
    got_body = values.get(param.name)
    if got_body is None and not _is_explicit_null(param, values):
        # Not provided. (None for a parameter that cannot be null also means "not provided".)
        if param.field.field_info.is_required():
            raise MissingParamError(param=param.name)
        got_body = param.field.get_default()
    body_type = param.field.field_info.annotation
    check_type = get_origin(body_type) or body_type
    # Union members may not all be runtime-checkable classes, so unions are
    # skipped. typing.Union's origin is not a class and falls out of the
    # isinstance(check_type, type) check; PEP 604 unions (X | Y) have
    # types.UnionType as origin, which IS a class, so exclude it explicitly.
    if (
        body_type is not None
        and check_type is not UnionType
        and isinstance(check_type, type)
        and not isinstance(got_body, check_type)
    ):
        raise WrongTypeError(field=param.name, type=body_type)
    return got_body


def _dump_json(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        # jsonable_encoder does exactly this dump and then walks the result again in Python.
        # Skipping that second pass keeps the output byte-identical (model_dump_json would
        # not: it writes non-finite floats as null, which the worker then rejects).
        return json.dumps(value.model_dump(mode="json", by_alias=True)).encode()
    return json.dumps(jsonable_encoder(value)).encode()


def _to_wire(value: Any) -> str:
    """Serialize a scalar the way FastAPI parses it back from a URL or header."""
    if type(value) is str:
        return value
    encoded = jsonable_encoder(value)
    if isinstance(encoded, bool):
        return "true" if encoded else "false"
    return str(encoded)


def _header_value(name: str, value: Any) -> str | None:
    if not isinstance(value, _COLLECTIONS):
        return _to_wire(value)
    if len(value) > 1:
        # Cloud Tasks and Cloud Scheduler send each header once, and FastAPI reads a list
        # header as one item per occurrence: it does not split a comma-separated value.
        raise ValueError(
            f"header {name!r} cannot carry {len(value)} values: a task request sends each header once. "
            "Send a single value, or move the list to a query parameter or the body"
        )
    return _to_wire(next(iter(value))) if value else None


@lru_cache(maxsize=128)
def _parse_base_url(base_url: str) -> ParseResult:
    return urlparse(base_url)
