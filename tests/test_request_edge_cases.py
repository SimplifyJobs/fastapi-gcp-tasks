"""
Round-trip tests for less common endpoint shapes.

Like ``test_request_building``, each test builds a request and replays it into the app,
asserting that the worker receives what the caller passed.
"""

# Standard Library Imports
import json
from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Any, TypedDict, cast
from unittest.mock import MagicMock
from urllib.parse import parse_qsl, urlsplit

# Third Party Imports
import pytest
from fastapi import APIRouter, Body, Cookie, Depends, FastAPI, Header, Query
from google.cloud import tasks_v2
from pydantic import AliasChoices, BaseModel, Field, SecretStr
from starlette.convertors import IntegerConvertor, register_url_convertor

# Imports from this repository
from fastapi_gcp_tasks import AsyncDelayedRouteBuilder, DelayedRouteBuilder, as_delayed_task, task_default_options
from fastapi_gcp_tasks.async_delayer import AsyncDelayer
from fastapi_gcp_tasks.delayer import Delayer
from tests.helpers import replay

ORIGIN = "https://worker.example.com"
QUEUE_PATH = "projects/test-project/locations/us-central1/queues/test-queue"

type MaybeStr = str | None
type Maybe[T] = T | None
type Identity[T] = T


class PaddedIntConvertor(IntegerConvertor):
    """A custom segment with its own URL form: four zero-padded digits."""

    regex = "[0-9]{4}"

    def to_string(self, value: int) -> str:
        """Write the number zero-padded to four digits."""
        return f"{value:04d}"


register_url_convertor("padded", PaddedIntConvertor())


class Item(BaseModel):
    """Simple body model."""

    name: str


class Event(BaseModel):
    """Body model holding free-form attributes."""

    attributes: dict[str, Any]


class Page[T](BaseModel):
    """Generic body model."""

    items: list[T]


class Payload(TypedDict):
    """TypedDict body."""

    name: str
    count: int


class ControlHeaders(BaseModel):
    """Header-parameter model that declares a header the task request sets itself."""

    x_tenant: str
    content_type: str | None = "text/plain"


class SortFilters(BaseModel):
    """Query-parameter model whose field is only accepted under other names."""

    sort: str = Field("asc", validation_alias=AliasChoices("order", "sort_order"))


def audited(item: Annotated[str | None, Query()] = None) -> str | None:
    """Dependency whose query param shares its name with an endpoint body param."""
    return item


def note_from_body(ref: Annotated[Item, Body(embed=True)]) -> str:
    """Dependency that reads a body param called ``ref``."""
    return ref.name


def ref_from_query(ref: Annotated[str | None, Query()] = None) -> str | None:
    """Another dependency that reads a query param also called ``ref``."""
    return ref


client = MagicMock(spec=tasks_v2.CloudTasksClient)
client.create_task.side_effect = lambda request, timeout: request


def _route_class(callback_base_url: str = ORIGIN) -> Any:
    return DelayedRouteBuilder(
        client=client, callback_base_url=callback_base_url, queue_path=QUEUE_PATH, auto_create_queue=False
    )


router = APIRouter(route_class=_route_class())
slash_router = APIRouter(route_class=_route_class(), prefix="/slashes")


@slash_router.post("/send_email/")
@as_delayed_task
def send_email(to: str) -> dict[str, Any]:
    """Route declared with a trailing slash."""
    return {"to": to}


@slash_router.post("/")
@as_delayed_task
def slash_index() -> dict[str, Any]:
    """Route at the router's root."""
    return {"ok": True}


@slash_router.post("/export/{prefix:path}")
@as_delayed_task
def export(prefix: str) -> dict[str, Any]:
    """Route whose path-converter value may end in a slash or be empty."""
    return {"prefix": prefix}


@router.post("/charge/{amount}")
@as_delayed_task
def charge(
    amount: Decimal,
    fee: Decimal,
    ttl: timedelta,
    x_tax: Annotated[Decimal, Header()],
    window: Annotated[timedelta, Cookie()],
) -> dict[str, Any]:
    """Echo Decimal and timedelta values from every non-body location."""
    return {
        "amount": str(amount),
        "fee": str(fee),
        "ttl": ttl.total_seconds(),
        "x_tax": str(x_tax),
        "window": window.total_seconds(),
    }


@router.post("/ttl_default")
@as_delayed_task
def ttl_default(ttl: timedelta = timedelta(minutes=5)) -> dict[str, Any]:
    """Echo a timedelta query param that has a default."""
    return {"ttl": ttl.total_seconds()}


@router.post("/secret")
@as_delayed_task
def secret(api_key: SecretStr) -> None:
    """Take a secret as a query param."""


@router.post("/conv_int/{n:int}")
@as_delayed_task
def conv_int(n: int) -> dict[str, Any]:
    """Echo a Starlette int segment."""
    return {"n": n}


@router.post("/conv_float/{x:float}")
@as_delayed_task
def conv_float(x: float) -> dict[str, Any]:
    """Echo a Starlette float segment."""
    return {"x": x}


@router.post("/prices")
@as_delayed_task
def prices(prices: list[Decimal]) -> dict[str, Any]:
    """Echo a list of Decimals sent as the body."""
    return {"prices": [str(price) for price in prices]}


@router.post("/tip")
@as_delayed_task
def tip(item: Item, tip: Annotated[Decimal, Body()]) -> dict[str, Any]:
    """Echo a scalar Decimal sent next to a model."""
    return {"item": item.name, "tip": str(tip)}


@router.post("/dict_body")
@as_delayed_task
def dict_body(payload: dict[str, Any]) -> dict[str, Any]:
    """Echo a free-form dict body."""
    return payload


@router.post("/events")
@as_delayed_task
def events(events: list[Event]) -> dict[str, Any]:
    """Echo a list of models."""
    return {"attributes": [event.attributes for event in events]}


@router.post("/typed_dict")
@as_delayed_task
def typed_dict(payload: Payload) -> dict[str, Any]:
    """Echo a TypedDict body."""
    return dict(payload)


@router.post("/weight")
@as_delayed_task
def weight(item: Item, weight: Annotated[float, Body()]) -> dict[str, Any]:
    """Echo a float body param."""
    return {"item": item.name, "weight": weight}


@router.post("/page")
@as_delayed_task
def page(page: Page[Item]) -> dict[str, Any]:
    """Echo a generic model body."""
    return {"items": [item.name for item in page.items]}


@router.post("/retry_aware")
@as_delayed_task
def retry_aware(x_cloudtasks_taskretrycount: Annotated[int, Header()] = 0) -> dict[str, Any]:
    """Read a header that Cloud Tasks sets."""
    return {"retry": x_cloudtasks_taskretrycount}


@router.post("/content_type")
@as_delayed_task
def content_type(content_type: Annotated[str, Header()] = "text/plain") -> dict[str, Any]:
    """Read the request's content type."""
    return {"content_type": content_type}


@router.post("/list_header_default")
@as_delayed_task
def list_header_default(x_ids: Annotated[list[int], Header(default_factory=lambda: [1, 2])]) -> dict[str, Any]:
    """Echo a list header whose default has several values."""
    return {"x_ids": x_ids}


@router.post("/collide")
@as_delayed_task
def collide(item: Item, audited_item: str | None = Depends(audited)) -> dict[str, Any]:
    """Endpoint body param ``item`` plus a dependency query param also called ``item``."""
    return {"item": item.name, "audited": audited_item}


@router.post("/alias695")
@as_delayed_task
def alias695(item: Item, note: Annotated[MaybeStr, Body()] = "keep") -> dict[str, Any]:
    """Nullable body param declared through a ``type`` alias."""
    return {"item": item.name, "note": note}


@router.post("/alias695_generic")
@as_delayed_task
def alias695_generic(item: Item, note: Annotated[Maybe[str], Body()] = "keep") -> dict[str, Any]:
    """Nullable body param declared through a specialized generic ``type`` alias."""
    return {"item": item.name, "note": note}


@router.post("/control_headers")
@as_delayed_task
def control_headers(headers: Annotated[ControlHeaders, Header()]) -> dict[str, Any]:
    """Echo a header-parameter model."""
    return {"x_tenant": headers.x_tenant}


@router.post("/control_headers_default")
@as_delayed_task
def control_headers_default(
    headers: Annotated[ControlHeaders, Header()] = ControlHeaders(x_tenant="dm", content_type="text/plain"),  # noqa: B008
) -> dict[str, Any]:
    """Header-parameter model whose endpoint default sets a reserved field."""
    return {"x_tenant": headers.x_tenant}


@router.post("/padded/{n:padded}")
@as_delayed_task
def padded(n: int) -> dict[str, Any]:
    """Echo a custom numeric segment."""
    return {"n": n}


@router.post("/loose_int/{n:int}")
@as_delayed_task
def loose_int(n: float) -> dict[str, Any]:
    """An int segment whose parameter is (mistakenly) typed as a float."""
    return {"n": n}


@router.post("/decimal_float/{x:float}")
@as_delayed_task
def decimal_float(x: Decimal) -> dict[str, Any]:
    """A float segment whose parameter is typed as a Decimal."""
    return {"x": str(x)}


@router.post("/alias695_identity")
@as_delayed_task
def alias695_identity(item: Item, note: Annotated[Identity[str | None], Body()] = "keep") -> dict[str, Any]:
    """Nullable body param whose nullability comes from a generic alias's argument."""
    return {"item": item.name, "note": note}


@router.post("/two_dependencies")
@as_delayed_task
def two_dependencies(
    body_ref: str = Depends(note_from_body), query_ref: str | None = Depends(ref_from_query)
) -> dict[str, Any]:
    """Two dependencies that each read a parameter called ``ref`` from a different place."""
    return {"body_ref": body_ref, "query_ref": query_ref}


@router.post("/sorted")
@as_delayed_task
def sorted_task(filters: Annotated[SortFilters, Query()]) -> dict[str, Any]:
    """Echo a query-parameter model that uses AliasChoices."""
    return filters.model_dump()


@router.post("/plain")
@as_delayed_task
def plain(q: str | None = None) -> dict[str, Any]:
    """Echo an optional query param."""
    return {"q": q}


app = FastAPI()
app.include_router(router)
app.include_router(slash_router)


def _http(request: Any) -> Any:
    return request.task.http_request


def _query(http_request: Any) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(http_request.url).query, keep_blank_values=True)


class TestTrailingSlash:
    """The task URL must be the route's own path, including a trailing slash."""

    def test_route_declared_with_a_trailing_slash(self) -> None:
        """Without the slash the worker answers with a redirect instead of running the task."""
        http = _http(send_email.delay(to="dwight@example.com"))
        assert urlsplit(http.url).path == "/slashes/send_email/"
        assert replay(app, http) == (200, {"to": "dwight@example.com"})

    def test_route_at_the_router_root(self) -> None:
        """A route registered as "/" under a prefix keeps its slash."""
        http = _http(slash_index.delay())
        assert urlsplit(http.url).path == "/slashes/"
        assert replay(app, http) == (200, {"ok": True})

    def test_path_converter_value_ending_in_a_slash(self) -> None:
        """The slash is part of the value, not decoration."""
        http = _http(export.delay(prefix="reports/2026/"))
        assert replay(app, http) == (200, {"prefix": "reports/2026/"})

    def test_empty_path_converter_value(self) -> None:
        """``{prefix:path}`` matches an empty value, so it can be sent."""
        http = _http(export.delay(prefix=""))
        assert replay(app, http) == (200, {"prefix": ""})


class TestScalarTypes:
    """Values outside the body are sent in a form Pydantic parses back to the same value."""

    def test_decimal_and_timedelta_keep_their_value(self) -> None:
        """Decimals used to go through float, and timedeltas were sent as a float the worker rejects."""
        http = _http(
            charge.delay(
                amount=Decimal("12345678901234567890.12"),
                fee=Decimal("0.10"),
                ttl=timedelta(hours=1),
                x_tax=Decimal("0.1234567890123456789"),
                window=timedelta(minutes=5),
            )
        )
        assert replay(app, http) == (
            200,
            {
                "amount": "12345678901234567890.12",
                "fee": "0.10",
                "ttl": 3600.0,
                "x_tax": "0.1234567890123456789",
                "window": 300.0,
            },
        )

    def test_timedelta_default_can_be_triggered(self) -> None:
        """A sent default must be parseable too, or the endpoint could never be triggered."""
        assert replay(app, _http(ttl_default.delay())) == (200, {"ttl": 300.0})

    def test_secret_outside_the_body_is_rejected(self) -> None:
        """Pydantic masks a secret when serializing it, so the worker would receive asterisks."""
        with pytest.raises(ValueError, match="secret"):
            secret.delay(api_key=SecretStr("hunter2"))


class TestTypedPathSegments:
    """Starlette's typed segments only match their own canonical form."""

    def test_int_segment(self) -> None:
        """A non-negative int is sent as is."""
        assert replay(app, _http(conv_int.delay(n=5))) == (200, {"n": 5})

    def test_negative_int_cannot_match(self) -> None:
        """``{n:int}`` never matches a negative number, so fail at the call site instead of on a 404."""
        with pytest.raises(ValueError, match="'n'"):
            conv_int.delay(n=-5)

    def test_small_float_uses_plain_notation(self) -> None:
        """``{x:float}`` does not match exponent notation."""
        http = _http(conv_float.delay(x=1e-7))
        assert replay(app, http) == (200, {"x": 1e-7})

    @pytest.mark.parametrize("x", [1.1111111111111112e-5, 1e-21, 0.1, 3.14, 5.0, 1e22, 123456789.12345679])
    def test_float_segment_keeps_every_digit(self, x: float) -> None:
        """Plain notation must not round: the worker has to parse back the exact float."""
        http = _http(conv_float.delay(x=x))
        assert replay(app, http) == (200, {"x": x})

    def test_integral_float_keeps_its_spelling(self) -> None:
        """A whole number stays "/5", so a scheduled job with that URL is not seen as changed."""
        assert urlsplit(_http(conv_float.delay(x=5.0)).url).path == "/conv_float/5"

    def test_custom_numeric_segment_uses_its_own_format(self) -> None:
        """A registered convertor decides how its values are written."""
        http = _http(padded.delay(n=5))
        assert urlsplit(http.url).path == "/padded/0005"
        assert replay(app, http) == (200, {"n": 5})

    def test_whole_number_float_fits_an_int_segment(self) -> None:
        """5.0 is exactly 5, so the int segment can carry it."""
        http = _http(loose_int.delay(n=5.0))
        assert urlsplit(http.url).path == "/loose_int/5"
        assert replay(app, http) == (200, {"n": 5.0})

    def test_decimal_on_a_float_segment(self) -> None:
        """A Decimal is a number too: it is written in plain notation, not left as "1E-7"."""
        http = _http(decimal_float.delay(x=Decimal("1E-7")))
        assert urlsplit(http.url).path == "/decimal_float/0.0000001"
        assert replay(app, http) == (200, {"x": "1E-7"})

    def test_fraction_is_not_truncated_into_an_int_segment(self) -> None:
        """1.5 must not become "/1": the segment cannot carry it, so fail at the call site."""
        with pytest.raises(ValueError, match="'n'"):
            loose_int.delay(n=1.5)

    @pytest.mark.parametrize("x", [-1.5, float("inf"), float("nan")])
    def test_float_the_segment_cannot_match(self, x: float) -> None:
        """``{x:float}`` has no form for a sign or a non-finite value."""
        with pytest.raises(ValueError, match="'x'"):
            conv_float.delay(x=x)


class TestBodiesThatAreNotASingleModel:
    """Bodies other than one top-level model are serialized the same way a model is."""

    def test_list_of_decimals(self) -> None:
        """Decimals in a plain list keep their digits."""
        http = _http(prices.delay(prices=[Decimal("0.10"), Decimal("12345678901234567890.12")]))
        assert replay(app, http) == (200, {"prices": ["0.10", "12345678901234567890.12"]})

    def test_scalar_decimal_next_to_a_model(self) -> None:
        """A scalar body param is not routed through float either."""
        http = _http(tip.delay(item=Item(name="chili"), tip=Decimal("12345678901234567890.12")))
        assert replay(app, http) == (200, {"item": "chili", "tip": "12345678901234567890.12"})

    def test_dict_keys_are_not_filtered(self) -> None:
        """Keys starting with "_sa" used to be dropped from dict bodies."""
        payload = {"_sale_price": 5, "_saved": True, "sku": "x"}
        assert replay(app, _http(dict_body.delay(payload=payload))) == (200, payload)

    def test_list_of_models_matches_a_single_model(self) -> None:
        """The same model keeps the same keys whether it is sent alone or in a list."""
        attributes = {"_sale_price": 5, "sku": "x"}
        http = _http(events.delay(events=[Event(attributes=attributes)]))
        assert replay(app, http) == (200, {"attributes": [attributes]})

    def test_typed_dict_body(self) -> None:
        """A TypedDict cannot be isinstance-checked, which used to crash the call."""
        http = _http(typed_dict.delay(payload={"name": "chili", "count": 2}))
        assert replay(app, http) == (200, {"name": "chili", "count": 2})

    def test_int_for_a_float_body_param(self) -> None:
        """An int is a valid float argument for type checkers and for the worker."""
        http = _http(weight.delay(item=Item(name="chili"), weight=5))
        assert replay(app, http) == (200, {"item": "chili", "weight": 5.0})

    def test_generic_model_instance(self) -> None:
        """``Page(...)`` is a valid argument for a ``Page[Item]`` parameter."""
        http = _http(page.delay(page=Page(items=[Item(name="a")])))
        assert replay(app, http) == (200, {"items": ["a"]})

    def test_nullable_through_a_specialized_generic_alias(self) -> None:
        """``Maybe[str]`` for ``type Maybe[T] = T | None`` is nullable too."""
        http = _http(alias695_generic.delay(item=Item(name="a"), note=None))
        assert json.loads(http.body) == {"item": {"name": "a"}, "note": None}

    def test_nullable_through_a_generic_alias_argument(self) -> None:
        """``Identity[str | None]`` is nullable because its argument is."""
        http = _http(alias695_identity.delay(item=Item(name="a"), note=None))
        assert json.loads(http.body) == {"item": {"name": "a"}, "note": None}

    def test_nullable_through_a_type_alias(self) -> None:
        """``type MaybeStr = str | None`` is still nullable, so an explicit None is sent as null."""
        http = _http(alias695.delay(item=Item(name="a"), note=None))
        assert json.loads(http.body) == {"item": {"name": "a"}, "note": None}


class TestHeadersTheRequestControls:
    """Some headers belong to the task request itself and cannot be task arguments."""

    def test_cloud_tasks_header_cannot_be_passed(self) -> None:
        """Cloud Tasks sets it on dispatch, so a value passed here was silently dropped."""
        with pytest.raises(TypeError, match="x_cloudtasks_taskretrycount"):
            retry_aware.delay(x_cloudtasks_taskretrycount=3)

    def test_content_type_is_always_json(self) -> None:
        """A declared content-type header must not add a second, conflicting header."""
        http = _http(content_type.delay())
        assert [name for name in http.headers if name.lower() == "content-type"] == ["Content-Type"]
        assert replay(app, http) == (200, {"content_type": "application/json"})

        with pytest.raises(TypeError, match="content_type"):
            content_type.delay(content_type="text/csv")

    def test_reserved_header_in_a_header_model(self) -> None:
        """A header model cannot smuggle in a header the request controls either."""
        http = _http(control_headers.delay(headers=ControlHeaders(x_tenant="dm")))
        assert [name for name in http.headers if name.lower() == "content-type"] == ["Content-Type"]
        assert http.headers["x-tenant"] == "dm"

        with pytest.raises(TypeError, match="content_type"):
            control_headers.delay(headers=ControlHeaders(x_tenant="dm", content_type="text/csv"))

    def test_reserved_header_set_to_none_in_a_header_model(self) -> None:
        """Setting the field at all is the mistake, whatever the value."""
        with pytest.raises(TypeError, match="content_type"):
            control_headers.delay(headers=ControlHeaders(x_tenant="dm", content_type=None))

    def test_reserved_header_in_the_endpoint_default_model(self) -> None:
        """A field the endpoint's own default sets was not passed by the caller, so it must not block the call."""
        http = _http(control_headers_default.delay())
        assert http.headers["x-tenant"] == "dm"
        assert [name for name in http.headers if name.lower() == "content-type"] == ["Content-Type"]


class TestDefaultsThatCannotBeSent:
    """A default the request cannot express is left to the worker instead of blocking the call."""

    def test_multi_value_header_default(self) -> None:
        """The caller passed nothing, so nothing is sent and the worker applies the same default."""
        # The default comes from Header(default_factory=...), which the signature cannot show a type checker
        http = _http(list_header_default.delay())  # type: ignore[call-arg]
        assert "x-ids" not in http.headers
        assert replay(app, http) == (200, {"x_ids": [1, 2]})

    def test_explicit_multi_value_header_is_still_rejected(self) -> None:
        """An explicit value that cannot be sent is the caller's mistake."""
        with pytest.raises(ValueError, match="x-ids"):
            list_header_default.delay(x_ids=[3, 4])


class TestNames:
    """How argument names map to parameters."""

    def test_endpoint_parameter_wins_over_a_dependency_parameter(self) -> None:
        """The endpoint's ``item`` body is the task argument; the dependency's query ``item`` is not."""
        http = _http(collide.delay(item=Item(name="a")))
        assert replay(app, http) == (200, {"item": "a", "audited": None})

    def test_body_parameter_wins_over_a_dependency_parameter(self) -> None:
        """The body is the caller's to supply, so a name it uses is the body's, whichever dependency declares it."""
        http = _http(two_dependencies.delay(ref=Item(name="r-1")))  # type: ignore[call-arg]
        assert _query(http) == []
        assert replay(app, http) == (200, {"body_ref": "r-1", "query_ref": None})

    def test_alias_choices_in_a_parameter_model(self) -> None:
        """A field that is only accepted under its alias choices is sent under the first one."""
        http = _http(sorted_task.delay(filters=SortFilters(order="desc")))
        assert _query(http) == [("order", "desc")]
        assert replay(app, http) == (200, {"sort": "desc"})


class TestCallbackBaseUrl:
    """Options that decide where the task is sent."""

    def test_blank_query_values_are_kept(self) -> None:
        """Query params without a value are still part of the callback URL."""
        http = _http(plain.options(callback_base_url=f"{ORIGIN}?tenant=dm&debug=&dry_run").delay(q="x"))
        assert _query(http) == [("tenant", "dm"), ("debug", ""), ("dry_run", ""), ("q", "x")]

    def test_per_call_callback_base_url_replaces_an_endpoint_base_url(self) -> None:
        """Each layer passes one of the two names; mixing them across layers is not a conflict."""
        layered = APIRouter(route_class=_route_class())

        @layered.post("/layered")
        @task_default_options(base_url="https://default.example.com")
        @as_delayed_task
        def layered_task() -> None:
            """Task with an endpoint-level URL under the legacy name."""

        delayer = cast(Delayer, layered_task.options(callback_base_url="https://override.example.com"))
        assert delayer.base_url == "https://override.example.com"

    def test_per_call_base_url_replaces_an_endpoint_callback_base_url(self) -> None:
        """The same holds with the two names the other way round."""
        layered = APIRouter(route_class=_route_class())

        @layered.post("/layered")
        @task_default_options(callback_base_url="https://default.example.com")
        @as_delayed_task
        def layered_task() -> None:
            """Task with an endpoint-level URL under the current name."""

        delayer = cast(Delayer, layered_task.options(base_url="https://override.example.com"))
        assert delayer.base_url == "https://override.example.com"

    def test_per_call_url_replaces_the_endpoint_default_on_async_routes(self) -> None:
        """The async builder layers the two names the same way."""
        layered = APIRouter(route_class=AsyncDelayedRouteBuilder(callback_base_url=ORIGIN, queue_path=QUEUE_PATH))

        @layered.post("/layered")
        @task_default_options(base_url="https://default.example.com")
        async def layered_task() -> None:
            """Task with an endpoint-level URL."""

        delayer = cast(AsyncDelayer, cast(Any, layered_task).options(callback_base_url="https://override.example.com"))
        assert delayer.base_url == "https://override.example.com"
