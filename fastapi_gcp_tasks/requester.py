# Standard Library Imports
import inspect
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from functools import lru_cache, partial
from http.cookies import SimpleCookie
from types import UnionType
from typing import Annotated, Any, TypeAliasType, Union, get_args, get_origin
from urllib.parse import ParseResult, parse_qsl, quote, urlencode, urlparse, urlunparse

# Third Party Imports
from fastapi import params
from fastapi.dependencies.models import Dependant
from fastapi.encoders import jsonable_encoder
from fastapi.routing import APIRoute
from pydantic import AliasChoices, BaseModel, SecretBytes, SecretStr
from pydantic_core import to_jsonable_python
from starlette.convertors import FloatConvertor, IntegerConvertor, StringConvertor

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
# The body is always JSON, so the request's content type is not a task argument either
_RESERVED_HEADERS = ("content-type",)

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
    # Starlette's convertor for the segment, and its pattern compiled once
    convertor: Any
    pattern: re.Pattern[str]


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
    # Header params the task request sets itself; they can be declared but not passed
    reserved: frozenset[str]


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
            reserved = sorted(name for name in unexpected if name in plan.reserved)
            if reserved:
                raise TypeError(
                    f"{plan.endpoint_name}() cannot take {', '.join(map(repr, reserved))} when triggered as a task: "
                    "the task request sets that header itself (Cloud Tasks and Cloud Scheduler set their own "
                    "headers on dispatch, and Content-Type is always application/json)"
                )
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
            pairs = (
                _expand_model(param, value, location="header", header=True) if param.is_model else [(param.wire, value)]
            )
            explicit = values.get(param.name) is not None
            for key, item in pairs:
                header_value = _header_value(key, item, explicit=explicit)
                if header_value is not None:
                    headers[key] = header_value

        cookies: list[str] = []
        for param in plan.cookies:
            value = _resolve(param, values, location="cookie")
            if value is None:
                continue
            pairs = _expand_model(param, value, location="cookie") if param.is_model else [(param.wire, value)]
            explicit = values.get(param.name) is not None
            for key, item in pairs:
                if isinstance(item, _COLLECTIONS):
                    if item and explicit:
                        # FastAPI reads a cookie as one string, which never validates as a list
                        raise ValueError(f"cookie {key!r} cannot carry a collection: a cookie holds a single value")
                    # Empty, or a default the request cannot express: the worker applies its own default
                    continue
                # Quote like the stdlib does, so a ";" or "," in a value cannot end it early
                cookies.append(f"{key}={_COOKIES.value_encode(_to_wire(item))[1]}")
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
            # Percent-encode so reserved characters stay inside the segment instead
            # of being read as a query string or a fragment.
            encoded = quote(_path_segment(path_param, value), safe="/")
            path = path.replace("{" + path_param.key + "}", encoded)

        query: list[tuple[str, str]] = []
        set_keys: set[str] = set()
        for param in plan.query:
            value = _resolve(param, values, location="query")
            if value is None:
                continue
            pairs = _expand_model(param, value, location="query") if param.is_model else [(param.wire, value)]
            explicit = values.get(param.name) is not None
            for key, item in pairs:
                if isinstance(item, _COLLECTIONS):
                    elements = [_to_wire(element) for element in item]
                    if isinstance(item, (set, frozenset)):
                        # Sets have no stable order; sort so the same call always builds the same URL
                        elements.sort()
                else:
                    elements = [_to_wire(item)]
                if elements or explicit:
                    # This key replaces the same key on the base url. An omitted argument whose
                    # default is empty sends nothing, so it leaves the base url's value in place.
                    set_keys.add(key)
                query.extend((key, element) for element in elements)

        # Note: you might think urljoin is a better solution here, it is not.
        base = _parse_base_url(self.base_url)
        # Only the leading slash is ours to remove: a trailing one is part of the route
        # ("/send_email/") or of a path value, and the worker redirects or 404s without it.
        full_path = base.path.strip("/") + "/" + path.lstrip("/")
        if base.query:
            # Keep query params from the base url unless the task sets the same key
            inherited = parse_qsl(base.query, keep_blank_values=True)
            query = [pair for pair in inherited if pair[0] not in set_keys] + query
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
    declared_body = collect("body_params", group=False)
    # The JSON body is one document that only the caller can supply, so every body param
    # is treated as the endpoint's own, even when a dependency declares it
    body = tuple(
        _Param(
            name=p.name,
            wire=p.wire,
            field=p.field,
            own=True,
            nullable=_accepts_none(p.field.field_info.annotation),
        )
        for p in declared_body
    )
    path_fields = collect("path_params", group=False)

    path = tuple(_path_param(key, convertor, path_fields) for key, convertor in route.param_convertors.items())

    # An argument name belongs to the endpoint's own parameter first: a dependency parameter
    # that happens to share the name (in another location) is not what the caller means.
    own_names = {param.name for param in (*query, *all_headers, *cookies, *declared_body) if param.own} | {
        param.name for param in path
    }
    query, all_headers, cookies = (
        tuple(param for param in group if param.own or param.name not in own_names)
        for group in (query, all_headers, cookies)
    )
    headers = tuple(param for param in all_headers if not _is_reserved_header(param.wire))

    accepted = frozenset([param.name for param in (*query, *headers, *cookies, *body)] + [param.name for param in path])
    reserved = frozenset(param.name for param in all_headers if _is_reserved_header(param.wire)) - accepted
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
        injected = frozenset(signature.parameters) - accepted - reserved

    return _RoutePlan(
        endpoint_name=getattr(route.endpoint, "__name__", "task"),
        path=path,
        query=query,
        headers=headers,
        cookies=cookies,
        body=body,
        # A lone, non-embedded body param is used by FastAPI as the body field itself;
        # anything else is wrapped in a synthetic model keyed by parameter name.
        embed_body=bool(body) and not any(route.body_field is param.field for param in body),
        form_body=any(isinstance(param.field.field_info, params.Form) for param in body),
        positional=positional,
        accepted=accepted,
        injected=injected,
        reserved=reserved,
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
        convertor=convertor,
        pattern=re.compile(convertor.regex),
    )


def _path_segment(path_param: _PathParam, value: Any) -> str:
    """Return the text for a path segment, or raise if the route's own pattern would not match it."""
    convertor = path_param.convertor
    segment = _to_wire(value)
    # Starlette's typed segments match one canonical form only (no sign, no exponent)
    try:
        if isinstance(convertor, IntegerConvertor):
            segment = str(int(value))
        elif isinstance(convertor, FloatConvertor):
            # The shortest text that parses back to the same float, written without an exponent.
            # (Starlette's own to_string keeps 20 decimal places and would round small values.)
            segment = format(Decimal(repr(float(value))), "f")
    except (TypeError, ValueError, InvalidOperation):
        pass  # not representable: the pattern check below reports it
    if not path_param.pattern.fullmatch(segment):
        # ASGI servers decode %2F before routing, so percent-encoding cannot rescue a value
        # the segment does not match: the request would hit a 404 or a different route.
        hint = ""
        if "/" in segment and isinstance(convertor, StringConvertor):
            hint = f"; declare the segment as '{{{path_param.key}:path}}' to allow slashes"
        raise ValueError(
            f"path parameter {path_param.name!r} cannot be sent as {segment!r}: "
            f"the route segment would not match it{hint}"
        )
    return segment


def _is_reserved_header(wire: str) -> bool:
    lowered = wire.lower()
    return lowered in _RESERVED_HEADERS or lowered.startswith(_RESERVED_HEADER_PREFIXES)


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


def _accepts_none(annotation: Any) -> bool:
    """
    Whether a parameter annotated this way can hold None.

    Decided from the annotation alone: probing the field with None would run the
    endpoint's own validators on a value the caller never passed.
    """
    if annotation is Any or annotation is object or annotation is None or annotation is type(None):
        return True
    if isinstance(annotation, TypeAliasType):
        # type MaybeStr = str | None
        return _accepts_none(annotation.__value__)
    origin = get_origin(annotation)
    if isinstance(origin, TypeAliasType):
        # Maybe[str], for type Maybe[T] = T | None
        return _accepts_none(origin.__value__)
    if origin is Annotated:
        return _accepts_none(get_args(annotation)[0])
    if origin in (Union, UnionType):
        return any(_accepts_none(member) for member in get_args(annotation))
    return False


def _require_deliverable(
    value: Any, *, location: str, name: str, required: bool, get_default: Callable[[], Any]
) -> None:
    """
    Reject an empty collection the worker would not receive as empty.

    An empty collection has no representation in a URL or header: the key is simply
    absent, so the worker falls back to its own default. That is only the same value
    when the default is empty too. The default is only resolved in that case, so
    default factories do not run for values that can be sent as they are.
    """
    if not isinstance(value, _COLLECTIONS) or value:
        return
    default = None if required else get_default()
    if required or not isinstance(default, _COLLECTIONS) or default:
        outcome = "reject the request" if required else f"use its default ({default!r})"
        raise ValueError(
            f"{location} parameter {name!r} cannot be sent as an empty collection: the worker would {outcome} instead"
        )


def _model_field_default(info: Any, model: BaseModel) -> Any:
    if getattr(info, "default_factory_takes_validated_data", False):
        # A factory that computes its default from the model's other fields
        return info.get_default(call_default_factory=True, validated_data=dict(model))
    return info.get_default(call_default_factory=True)


def _model_field_alias(info: Any, name: str) -> str:
    validation_alias = info.validation_alias
    if isinstance(validation_alias, AliasChoices):
        # Only the listed names are accepted, and any of them will do: use the first plain one
        validation_alias = next((choice for choice in validation_alias.choices if isinstance(choice, str)), None)
    if isinstance(validation_alias, str) and validation_alias:
        return validation_alias
    alias: str = info.alias or name
    return alias


def _expand_model(param: _Param, value: Any, *, location: str, header: bool = False) -> list[tuple[str, Any]]:
    """Flatten a parameter model into its individual (wire name, value) params."""
    convert_underscores = header and getattr(param.field.field_info, "convert_underscores", True)
    pairs: list[tuple[str, Any]] = []
    for name, info in type(value).model_fields.items():
        item = getattr(value, name)
        if item is None:
            continue
        _require_deliverable(
            item,
            location=location,
            name=f"{param.name}.{name}",
            required=info.is_required(),
            get_default=partial(_model_field_default, info, value),
        )
        key = _model_field_alias(info, name)
        if convert_underscores and key == name:
            key = key.replace("_", "-")
        if header and _is_reserved_header(key):
            if name in value.model_fields_set:
                raise TypeError(
                    f"{param.name}.{name} cannot be sent when triggered as a task: the task request sets "
                    f"the {key!r} header itself"
                )
            # Only declared so the worker can read it: nothing to send
            continue
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
    _require_deliverable(
        value,
        location=location,
        name=param.name,
        required=param.field.field_info.is_required(),
        get_default=param.field.get_default,
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
    if not _has_declared_type(got_body, body_type):
        raise WrongTypeError(field=param.name, type=body_type)
    return got_body


def _has_declared_type(value: Any, declared: Any) -> bool:
    """A cheap check that a body argument is the kind of object the endpoint declares."""
    check_type = get_origin(declared) or declared
    # Union members may not all be runtime-checkable classes, so unions are
    # skipped. typing.Union's origin is not a class and falls out of the
    # isinstance(check_type, type) check; PEP 604 unions (X | Y) have
    # types.UnionType as origin, which IS a class, so exclude it explicitly.
    if declared is None or check_type is UnionType or not isinstance(check_type, type):
        return True
    # Page[Item] is its own class; an instance built as Page(...) is still a valid argument
    generic_origin = getattr(check_type, "__pydantic_generic_metadata__", {}).get("origin")
    if generic_origin is not None:
        check_type = generic_origin
    if check_type is float and isinstance(value, int) and not isinstance(value, bool):
        return True
    try:
        return isinstance(value, check_type)
    except TypeError:
        # TypedDict and similar types cannot be instance-checked
        return True


def _jsonable(value: Any) -> Any:
    """
    Convert a value to JSON-compatible Python the way Pydantic does for a model field.

    Models are dumped by alias, and Decimals, dates and durations become strings Pydantic
    parses back exactly. Non-finite floats stay floats, which the worker accepts (written
    as null they would be rejected). Types Pydantic does not know go to jsonable_encoder.
    """
    return to_jsonable_python(value, by_alias=True, fallback=jsonable_encoder)


def _dump_json(value: Any) -> bytes:
    return json.dumps(_jsonable(value)).encode()


def _to_wire(value: Any) -> str:
    """Serialize a scalar the way FastAPI parses it back from a URL or header."""
    if type(value) is str:
        return value
    if isinstance(value, (SecretStr, SecretBytes)):
        raise ValueError(
            "a secret cannot be sent as a task argument: Pydantic masks it when it is serialized, "
            "so the worker would receive asterisks"
        )
    encoded = _jsonable(value)
    if isinstance(encoded, bool):
        return "true" if encoded else "false"
    return str(encoded)


def _header_value(name: str, value: Any, *, explicit: bool) -> str | None:
    if not isinstance(value, _COLLECTIONS):
        return _to_wire(value)
    if len(value) > 1:
        if not explicit:
            # A default the request cannot express: send nothing, the worker applies the same default
            return None
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
