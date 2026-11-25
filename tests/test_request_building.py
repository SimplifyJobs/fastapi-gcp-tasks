"""
Round-trip tests for the HTTP request that ``.delay()`` / ``.schedule()`` build.

Each test builds a request for an endpoint and replays it straight into the
FastAPI app, asserting that the worker receives exactly what the caller passed.
"""

# Standard Library Imports
import asyncio
import enum
import json
from datetime import datetime
from typing import Annotated, Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qsl, unquote, urlsplit

# Third Party Imports
import pytest
from fastapi import APIRouter, Body, Cookie, Depends, FastAPI, Form, Header, Path, Query
from fastapi.encoders import jsonable_encoder
from google.api_core.exceptions import NotFound
from google.cloud import scheduler_v1, tasks_v2
from pydantic import BaseModel, Field

# Imports from this repository
from fastapi_gcp_tasks import (
    AsyncDelayedRouteBuilder,
    CloudTasksHeaders,
    DelayedRouteBuilder,
    ScheduledRouteBuilder,
    as_async_delayed_task,
    as_delayed_task,
    as_scheduled_task,
)
from fastapi_gcp_tasks.exception import MissingParamError, WrongTypeError

CALLBACK_BASE_URL = "https://worker.example.com/tasks"
QUEUE_PATH = "projects/test-project/locations/us-central1/queues/test-queue"
LOCATION_PATH = "projects/test-project/locations/us-central1"


class Color(enum.Enum):
    """Enum used as a query parameter."""

    red = "red"
    blue = "blue"


class Item(BaseModel):
    """Simple body model."""

    name: str


class Other(BaseModel):
    """Second body model."""

    n: int


class Limits(BaseModel):
    """Body model with a float that may be non-finite."""

    limit: float


class Aliased(BaseModel):
    """Body model whose wire name differs from its attribute name."""

    full_name: str = Field(alias="fullName")


def pagination(page: int = 1) -> int:
    """Dependency that owns a query parameter."""
    return page


def require_token(x_token: str = Header()) -> str:
    """Dependency that owns a required header, usually supplied by a hook or by Cloud Tasks."""
    return x_token


client = MagicMock(spec=tasks_v2.CloudTasksClient)
client.create_task.side_effect = lambda request, timeout: request

router = APIRouter(
    route_class=DelayedRouteBuilder(
        client=client,
        callback_base_url=CALLBACK_BASE_URL,
        queue_path=QUEUE_PATH,
        auto_create_queue=False,
    )
)


@router.post("/opt_query")
@as_delayed_task
def opt_query(q: str | None = None, n: int | None = None, priority: int = 0) -> dict[str, Any]:
    """Echo optional and defaulted query params."""
    return {"q": q, "n": n, "priority": priority}


@router.post("/required_query")
@as_delayed_task
def required_query(n: int) -> dict[str, Any]:
    """Echo a required query param."""
    return {"n": n}


@router.post("/typed_query")
@as_delayed_task
def typed_query(
    ids: Annotated[list[int], Query()],
    color: Color,
    flag: bool,
    at: datetime,
) -> dict[str, Any]:
    """Echo non-string query params."""
    return {"ids": ids, "color": color.value, "flag": flag, "at": at.isoformat()}


@router.post("/aliased_query")
@as_delayed_task
def aliased_query(item_query: Annotated[str, Query(alias="item-query")]) -> dict[str, Any]:
    """Echo a query param with an explicit alias."""
    return {"item_query": item_query}


@router.post("/headers")
@as_delayed_task
def headers(
    x_request_id: Annotated[str, Header()],
    x_trace: Annotated[str | None, Header()] = None,
    raw_name: Annotated[str | None, Header(convert_underscores=False)] = None,
) -> dict[str, Any]:
    """Echo header params."""
    return {"x_request_id": x_request_id, "x_trace": x_trace, "raw_name": raw_name}


@router.post("/cookies")
@as_delayed_task
def cookies(
    session: Annotated[str | None, Cookie()] = None, theme: Annotated[str, Cookie()] = "light"
) -> dict[str, Any]:
    """Echo cookie params."""
    return {"session": session, "theme": theme}


@router.post("/branch/{name}")
@as_delayed_task
def branch(name: str) -> dict[str, Any]:
    """Echo a path param."""
    return {"name": name}


@router.post("/files/{rest:path}")
@as_delayed_task
def files(rest: str) -> dict[str, Any]:
    """Echo a path-converter param."""
    return {"rest": rest}


@router.post("/items/{itemId}")
@as_delayed_task
def aliased_path(item_id: Annotated[int, Path(alias="itemId")]) -> dict[str, Any]:
    """Echo a path param with an explicit alias."""
    return {"item_id": item_id}


@router.post("/one_body")
@as_delayed_task
def one_body(item: Item) -> dict[str, Any]:
    """Echo a single body."""
    return {"item": item.name}


@router.post("/aliased_body")
@as_delayed_task
def aliased_body(person: Aliased) -> dict[str, Any]:
    """Echo a body that serializes by alias."""
    return {"full_name": person.full_name}


@router.post("/two_bodies")
@as_delayed_task
def two_bodies(item: Item, other: Other, note: Annotated[str | None, Body()] = None) -> dict[str, Any]:
    """Echo several body params."""
    return {"item": item.name, "other": other.n, "note": note}


@router.post("/embedded")
@as_delayed_task
def embedded(item: Annotated[Item, Body(embed=True)]) -> dict[str, Any]:
    """Echo an embedded body."""
    return {"item": item.name}


@router.post("/mixed/{branch_name}")
@as_delayed_task
def mixed(branch_name: str, item: Item, priority: int = 0) -> dict[str, Any]:
    """Echo a mix of path, body and query params."""
    return {"branch_name": branch_name, "item": item.name, "priority": priority}


@router.post("/subdep")
@as_delayed_task
def subdep(page: int = Depends(pagination)) -> dict[str, Any]:
    """Echo a value resolved by a dependency."""
    return {"page": page}


@router.post("/guarded")
@as_delayed_task
def guarded(item: Item, token: str = Depends(require_token)) -> dict[str, Any]:
    """Echo a body behind a dependency that needs a header."""
    return {"item": item.name, "token": token}


@router.post("/with_ct_headers")
@as_delayed_task
def with_ct_headers(meta: CloudTasksHeaders = Depends()) -> dict[str, Any]:
    """Echo the retry count Cloud Tasks reports."""
    return {"retry_count": meta.retry_count}


@router.post("/aliased_header")
@as_delayed_task
def aliased_header(x_request_id: Annotated[str, Header(alias="x_request_id")]) -> dict[str, Any]:
    """Echo a header whose explicit alias keeps its underscores."""
    return {"x_request_id": x_request_id}


@router.post("/list_header")
@as_delayed_task
def list_header(x_ids: Annotated[list[int], Header()]) -> dict[str, Any]:
    """Echo a list-valued header."""
    return {"x_ids": x_ids}


@router.post("/set_query")
@as_delayed_task
def set_query(tags: Annotated[set[str], Query()]) -> dict[str, Any]:
    """Echo a set-valued query param."""
    return {"tags": sorted(tags)}


@router.post("/list_default_query")
@as_delayed_task
def list_default_query(ids: Annotated[list[int], Query(default_factory=list)]) -> dict[str, Any]:
    """Echo a list query param that defaults to empty."""
    return {"ids": ids}


@router.post("/nullable_bodies")
@as_delayed_task
def nullable_bodies(item: Item, note: Annotated[str | None, Body()] = "keep") -> dict[str, Any]:
    """Echo a nullable body param that has a non-null default."""
    return {"item": item.name, "note": note}


@router.post("/required_nullable_body")
@as_delayed_task
def required_nullable_body(item: Item, note: Annotated[str | None, Body()]) -> dict[str, Any]:
    """Echo a required body param that accepts null."""
    return {"item": item.name, "note": note}


@router.post("/limits")
@as_delayed_task
def limits(limits: Limits) -> dict[str, Any]:
    """Report whether the limit arrived as infinity."""
    return {"is_inf": limits.limit == float("inf")}


app = FastAPI()
app.include_router(router, prefix="/tasks")


def _replay(http_request: Any, *, extra_headers: dict[str, str] | None = None) -> tuple[int, Any]:
    """Send a built task request straight into the ASGI app and return (status, json body)."""
    target = getattr(http_request, "url", None) or http_request.uri
    parts = urlsplit(target)
    request_headers = {**dict(http_request.headers), **(extra_headers or {})}
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": parts.scheme,
        "path": unquote(parts.path),
        "raw_path": parts.path.encode(),
        "query_string": parts.query.encode(),
        "headers": [(k.lower().encode(), v.encode()) for k, v in request_headers.items()],
        "server": (parts.hostname, 443),
        "client": ("127.0.0.1", 1234),
    }
    sent: list[dict[str, Any]] = []
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": bytes(http_request.body), "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))  # type: ignore[arg-type]
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, json.loads(payload)


def _http(request: Any) -> Any:
    return request.task.http_request


def _query(http_request: Any) -> list[tuple[str, str]]:
    return parse_qsl(urlsplit(http_request.url).query, keep_blank_values=True)


class TestQueryParams:
    """Query parameters must reach the worker with the values the caller passed."""

    def test_omitted_optional_params_are_not_sent(self) -> None:
        """``None`` used to be stringified into the URL as the text "None"."""
        http = _http(opt_query.delay())
        assert _query(http) == [("priority", "0")]
        assert _replay(http) == (200, {"q": None, "n": None, "priority": 0})

    def test_explicit_none_is_not_sent(self) -> None:
        """Passing ``None`` explicitly behaves like leaving the argument out."""
        http = _http(opt_query.delay(q=None, n=None))
        assert _query(http) == [("priority", "0")]

    def test_given_optional_params_are_sent(self) -> None:
        """Provided values override the defaults."""
        http = _http(opt_query.delay(q="hi", n=3, priority=9))
        assert _replay(http) == (200, {"q": "hi", "n": 3, "priority": 9})

    def test_list_enum_bool_and_datetime(self) -> None:
        """Non-string values are serialized the way FastAPI parses them back."""
        at = datetime(2026, 1, 2, 3, 4, 5)
        http = _http(typed_query.delay(ids=[1, 2, 3], color=Color.blue, flag=True, at=at))
        assert [v for k, v in _query(http) if k == "ids"] == ["1", "2", "3"]
        assert _replay(http) == (200, {"ids": [1, 2, 3], "color": "blue", "flag": True, "at": at.isoformat()})

    def test_false_and_zero_are_sent(self) -> None:
        """Falsy values are real values, not "missing"."""
        http = _http(typed_query.delay(ids=[0], color=Color.red, flag=False, at=datetime(2026, 1, 1)))
        status, body = _replay(http)
        assert status == 200
        assert body["flag"] is False
        assert body["ids"] == [0]

    def test_alias_is_used_on_the_wire(self) -> None:
        """The caller uses the Python name; the URL uses the declared alias."""
        http = _http(aliased_query.delay(item_query="chili"))
        assert _query(http) == [("item-query", "chili")]
        assert _replay(http) == (200, {"item_query": "chili"})

    def test_missing_required_param_raises(self) -> None:
        """A required query param fails at the call site."""
        with pytest.raises(MissingParamError, match="n"):
            required_query.delay()  # type: ignore[call-arg]

    def test_invalid_value_raises(self) -> None:
        """Values are validated against the endpoint's annotation before a task is created."""
        with pytest.raises(ValueError, match="int"):
            required_query.delay(n="not a number")  # type: ignore[arg-type]

    def test_base_url_query_is_kept_and_overridden(self) -> None:
        """Query params on the callback base URL are preserved unless the task sets the same key."""
        http = _http(opt_query.options(callback_base_url=f"{CALLBACK_BASE_URL}?tenant=dm&priority=1").delay(q="hi"))
        assert sorted(_query(http)) == [("priority", "0"), ("q", "hi"), ("tenant", "dm")]


class TestHeaderAndCookieParams:
    """Header and cookie parameters must be sent under the names FastAPI reads."""

    def test_header_is_passed_by_python_name(self) -> None:
        """Required headers used to be impossible to pass; optional ones were dropped."""
        http = _http(headers.delay(x_request_id="abc", x_trace="t-1"))
        assert http.headers["x-request-id"] == "abc"
        assert http.headers["x-trace"] == "t-1"
        assert _replay(http) == (200, {"x_request_id": "abc", "x_trace": "t-1", "raw_name": None})

    def test_omitted_optional_header_is_not_sent(self) -> None:
        """An optional header that was not passed must not be sent as the text "None"."""
        http = _http(headers.delay(x_request_id="abc"))
        assert set(http.headers) == {"x-request-id", "Content-Type"}

    def test_convert_underscores_false_keeps_the_name(self) -> None:
        """``Header(convert_underscores=False)`` is sent with its literal name."""
        http = _http(headers.delay(x_request_id="abc", raw_name="kept"))
        assert http.headers["raw_name"] == "kept"

    def test_missing_required_header_raises(self) -> None:
        """A required header declared on the endpoint itself fails at the call site."""
        with pytest.raises(MissingParamError, match="x_request_id"):
            headers.delay()  # type: ignore[call-arg]

    def test_cookies_are_sent_in_the_cookie_header(self) -> None:
        """Cookies used to be sent under a non-standard ``Cookies`` header."""
        http = _http(cookies.delay(session="s3cr3t"))
        assert "Cookies" not in http.headers
        assert _replay(http) == (200, {"session": "s3cr3t", "theme": "light"})

    def test_cloud_tasks_headers_are_never_sent(self) -> None:
        """Headers owned by Cloud Tasks are left for Cloud Tasks to set."""
        http = _http(with_ct_headers.delay())
        assert set(http.headers) == {"Content-Type"}


class TestPathParams:
    """Path parameter values must be percent-encoded."""

    @pytest.mark.parametrize("name", ["Scranton PA", "a?admin=1#frag", "100%", "café", "{name}", "a&b=c"])
    def test_special_characters_round_trip(self, name: str) -> None:
        """Reserved characters stay inside the path segment instead of altering the URL."""
        http = _http(branch.delay(name=name))
        assert urlsplit(http.url).query == ""
        assert urlsplit(http.url).fragment == ""
        assert _replay(http) == (200, {"name": name})

    @pytest.mark.parametrize("name", ["a/b", ""])
    def test_values_the_route_cannot_match_are_rejected(self, name: str) -> None:
        """A slash or an empty value can never reach a plain ``{name}`` segment, so fail at the call site."""
        with pytest.raises(ValueError, match="name"):
            branch.delay(name=name)

    def test_path_converter_keeps_slashes(self) -> None:
        """``{rest:path}`` segments keep their slashes and encode everything else."""
        http = _http(files.delay(rest="reports/2026 Q1/final.pdf"))
        assert urlsplit(http.url).path == "/tasks/files/reports/2026%20Q1/final.pdf"
        assert _replay(http) == (200, {"rest": "reports/2026 Q1/final.pdf"})

    def test_aliased_path_param_uses_python_name(self) -> None:
        """A path param with an alias is passed by its Python name."""
        http = _http(aliased_path.delay(item_id=7))
        assert _replay(http) == (200, {"item_id": 7})

    def test_missing_path_param_raises(self) -> None:
        """A URL cannot be built without every path param."""
        with pytest.raises(MissingParamError, match="name"):
            branch.delay()  # type: ignore[call-arg]


class TestBodyParams:
    """Body parameters must produce the JSON shape FastAPI expects."""

    def test_single_body(self) -> None:
        """A single model is sent as the top-level JSON document."""
        http = _http(one_body.delay(item=Item(name="chili")))
        assert json.loads(http.body) == {"name": "chili"}
        assert _replay(http) == (200, {"item": "chili"})

    def test_single_body_serializes_by_alias(self) -> None:
        """Field aliases are used on the wire so the worker can validate the body."""
        http = _http(aliased_body.delay(person=Aliased(fullName="Kevin Malone")))
        assert json.loads(http.body) == {"fullName": "Kevin Malone"}
        assert _replay(http) == (200, {"full_name": "Kevin Malone"})

    def test_multiple_bodies_are_embedded(self) -> None:
        """Several body params used to fail with "field required: body"."""
        http = _http(two_bodies.delay(item=Item(name="chili"), other=Other(n=2)))
        assert json.loads(http.body) == {"item": {"name": "chili"}, "other": {"n": 2}}
        assert _replay(http) == (200, {"item": "chili", "other": 2, "note": None})

    def test_multiple_bodies_with_optional_scalar(self) -> None:
        """Optional scalar body params are embedded when provided."""
        http = _http(two_bodies.delay(item=Item(name="chili"), other=Other(n=2), note="extra onions"))
        assert _replay(http) == (200, {"item": "chili", "other": 2, "note": "extra onions"})

    def test_embed_true(self) -> None:
        """``Body(embed=True)`` wraps the model under its parameter name."""
        http = _http(embedded.delay(item=Item(name="chili")))
        assert json.loads(http.body) == {"item": {"name": "chili"}}
        assert _replay(http) == (200, {"item": "chili"})

    def test_missing_embedded_body_names_the_param(self) -> None:
        """The error names the missing parameter rather than a synthetic "body" field."""
        with pytest.raises(MissingParamError, match="other"):
            two_bodies.delay(item=Item(name="chili"))  # type: ignore[call-arg]

    def test_wrong_type_still_raises(self) -> None:
        """Passing something other than the declared model fails at the call site."""
        with pytest.raises(WrongTypeError):
            one_body.delay(item={"name": "chili"})  # type: ignore[arg-type]

    def test_form_params_are_rejected(self) -> None:
        """Form bodies cannot be delivered as JSON, so fail loudly instead of 422-ing on the worker."""
        form_router = APIRouter(
            route_class=DelayedRouteBuilder(
                client=client, callback_base_url=CALLBACK_BASE_URL, queue_path=QUEUE_PATH, auto_create_queue=False
            )
        )

        @form_router.post("/form")
        @as_delayed_task
        def form_task(name: Annotated[str, Form()]) -> None:
            """Task that takes form data."""

        with pytest.raises(TypeError, match="Form"):
            form_task.delay(name="chili")


class TestArgumentBinding:
    """``.delay()`` accepts the endpoint's own arguments and rejects everything else."""

    def test_positional_arguments(self) -> None:
        """Positional arguments typecheck, so they must work at runtime too."""
        http = _http(mixed.delay("scranton", Item(name="chili"), 5))
        assert _replay(http) == (200, {"branch_name": "scranton", "item": "chili", "priority": 5})

    def test_positional_and_keyword_arguments(self) -> None:
        """Positional and keyword arguments can be mixed like a normal call."""
        http = _http(mixed.delay("scranton", item=Item(name="chili")))
        assert _replay(http) == (200, {"branch_name": "scranton", "item": "chili", "priority": 0})

    def test_too_many_positional_arguments(self) -> None:
        """Extra positional arguments are an error, as in a normal call."""
        with pytest.raises(TypeError, match="positional"):
            mixed.delay("scranton", Item(name="chili"), 5, "extra")  # type: ignore[call-arg]

    def test_duplicate_argument(self) -> None:
        """An argument cannot be passed both positionally and by keyword."""
        with pytest.raises(TypeError, match="multiple values"):
            mixed.delay("scranton", branch_name="stamford", item=Item(name="chili"))  # type: ignore[misc]

    def test_unknown_keyword_raises(self) -> None:
        """Misspelled arguments used to be dropped silently."""
        with pytest.raises(TypeError, match="itm"):
            one_body.delay(itm=Item(name="chili"))  # type: ignore[call-arg]

    def test_options_then_positional(self) -> None:
        """Positional arguments also work after ``.options()``."""
        http = _http(mixed.options(countdown=5).delay("scranton", Item(name="chili")))
        assert _replay(http)[0] == 200


class TestDependencyParams:
    """Parameters owned by dependencies can be supplied, but are never required at the call site."""

    def test_dependency_query_param_is_forwarded(self) -> None:
        """A value passed for a dependency's query param used to be dropped."""
        http = _http(subdep.delay(page=7))
        assert _replay(http) == (200, {"page": 7})

    def test_dependency_defaults_are_left_to_the_worker(self) -> None:
        """Dependency params that were not passed are not added to the request."""
        http = _http(subdep.delay())
        assert _query(http) == []
        assert _replay(http) == (200, {"page": 1})

    def test_required_dependency_header_is_not_required_at_call_site(self) -> None:
        """Headers a dependency needs are typically added by a hook or by Cloud Tasks itself."""
        http = _http(guarded.delay(item=Item(name="chili")))
        assert _replay(http, extra_headers={"x-token": "from-hook"}) == (200, {"item": "chili", "token": "from-hook"})

    def test_dependency_header_can_be_passed_by_name(self) -> None:
        """A dependency's header can also be supplied explicitly by its Python name."""
        http = _http(guarded.delay(item=Item(name="chili"), x_token="explicit"))  # type: ignore[call-arg]
        assert _replay(http) == (200, {"item": "chili", "token": "explicit"})

    def test_injected_argument_cannot_be_passed(self) -> None:
        """A value for an argument the worker resolves itself would be dropped, so reject it."""
        with pytest.raises(TypeError, match="token"):
            guarded.delay(item=Item(name="chili"), token="nope")


def test_query_param_model_is_expanded() -> None:
    """A Pydantic model used as a query-parameter group is sent as individual query params."""

    class Filters(BaseModel):
        limit: int = 10
        tag: str | None = None

    model_router = APIRouter(
        route_class=DelayedRouteBuilder(
            client=client,
            callback_base_url="https://worker.example.com",
            queue_path=QUEUE_PATH,
            auto_create_queue=False,
        )
    )

    @model_router.post("/filtered")
    @as_delayed_task
    def filtered(filters: Annotated[Filters, Query()]) -> dict[str, Any]:
        """Echo a query-parameter model."""
        return filters.model_dump()

    http = _http(filtered.delay(filters=Filters(limit=5, tag="chili")))
    assert _query(http) == [("limit", "5"), ("tag", "chili")]

    # Unset optional fields are left out rather than sent as "None"
    assert _query(_http(filtered.delay(filters=Filters()))) == [("limit", "10")]


async def test_async_delay_binds_like_sync() -> None:
    """The async builder shares the same argument binding and request building."""
    async_client = MagicMock(spec=tasks_v2.CloudTasksAsyncClient)
    async_client.create_task = AsyncMock(return_value=tasks_v2.Task())
    async_router = APIRouter(
        route_class=AsyncDelayedRouteBuilder(
            client=async_client, callback_base_url=CALLBACK_BASE_URL, queue_path=QUEUE_PATH
        )
    )

    @async_router.post("/async/{name}")
    @as_async_delayed_task
    async def async_task(name: str, q: str | None = None) -> None:
        """Async task endpoint."""

    await async_task.delay("Scranton PA")
    request = async_client.create_task.call_args.kwargs["request"]
    assert request.task.http_request.url == f"{CALLBACK_BASE_URL}/async/Scranton%20PA"

    with pytest.raises(TypeError, match="nope"):
        await async_task.delay("x", nope=1)  # type: ignore[call-arg]


def test_schedule_binds_like_delay() -> None:
    """Scheduled jobs share the same argument binding and request building."""
    scheduler_client = MagicMock(spec=scheduler_v1.CloudSchedulerClient)
    scheduler_client.get_job.side_effect = NotFound("no job")
    scheduled_router = APIRouter(
        route_class=ScheduledRouteBuilder(
            client=scheduler_client, callback_base_url=CALLBACK_BASE_URL, location_path=LOCATION_PATH
        )
    )

    @scheduled_router.post("/pretzel_day/{branch_name}")
    @as_scheduled_task
    def pretzel_day(branch_name: str, item: Item, topping: str | None = None) -> None:
        """Scheduled task endpoint."""

    pretzel_day.scheduler(name="pretzel-day", schedule="0 9 * * 5").schedule("Scranton PA", item=Item(name="glaze"))
    job = scheduler_client.create_job.call_args.kwargs["request"].job
    assert job.http_target.uri == f"{CALLBACK_BASE_URL}/pretzel_day/Scranton%20PA"
    assert json.loads(job.http_target.body) == {"name": "glaze"}

    with pytest.raises(TypeError, match="toping"):
        pretzel_day.scheduler(name="pretzel-day", schedule="0 9 * * 5").schedule(  # type: ignore[call-arg]
            "Scranton", item=Item(name="glaze"), toping="salt"
        )


class TestCollections:
    """Collections must be sent in a form FastAPI reads back as the same collection."""

    def test_set_query_values_are_sorted(self) -> None:
        """Sets have no stable order; an unsorted URL would make identical scheduled jobs look changed."""
        http = _http(set_query.delay(tags={"cheese", "anchovy", "bacon"}))
        assert [value for _, value in _query(http)] == ["anchovy", "bacon", "cheese"]
        assert _replay(http) == (200, {"tags": ["anchovy", "bacon", "cheese"]})

    def test_empty_list_for_a_required_param_is_rejected(self) -> None:
        """An empty list leaves no key in the URL, so the worker would report the param as missing."""
        with pytest.raises(ValueError, match="ids"):
            typed_query.delay(ids=[], color=Color.red, flag=True, at=datetime(2026, 1, 1))

    def test_empty_list_equal_to_the_default_is_omitted(self) -> None:
        """When the worker's own default is also empty, leaving the key out delivers the same value."""
        http = _http(list_default_query.delay(ids=[]))
        assert _query(http) == []
        assert _replay(http) == (200, {"ids": []})

    def test_empty_list_overrides_the_base_url_value(self) -> None:
        """A key the caller set is not inherited from the callback base URL, even when it sends nothing."""
        http = _http(list_default_query.options(callback_base_url=f"{CALLBACK_BASE_URL}?ids=5").delay(ids=[]))
        assert _query(http) == []

    def test_single_item_list_header(self) -> None:
        """A one-item list fits in the single header occurrence a task can send."""
        http = _http(list_header.delay(x_ids=[7]))
        assert _replay(http) == (200, {"x_ids": [7]})

    def test_multi_value_list_header_is_rejected(self) -> None:
        """FastAPI does not split a comma-separated header back into a list, so fail at the call site."""
        with pytest.raises(ValueError, match="x-ids"):
            list_header.delay(x_ids=[1, 2])


class TestHeaderAndCookieEncoding:
    """Header names and cookie values must survive exactly as FastAPI expects them."""

    def test_explicit_alias_with_underscores_is_kept(self) -> None:
        """Only FastAPI's own default conversion applies; an explicit alias is used literally."""
        http = _http(aliased_header.delay(x_request_id="abc"))
        assert "x_request_id" in http.headers
        assert _replay(http) == (200, {"x_request_id": "abc"})

    @pytest.mark.parametrize("value", ["a;b", "a, b", 'say "hi"', "two words", "plain"])
    def test_cookie_values_are_quoted(self, value: str) -> None:
        """A ";" in a cookie value used to end the value early."""
        http = _http(cookies.delay(session=value, theme="dark"))
        assert _replay(http) == (200, {"session": value, "theme": "dark"})


class TestNullAndNonFiniteBodies:
    """JSON can express null and the worker accepts non-finite floats, so neither may be rewritten."""

    def test_explicit_none_is_sent_as_null(self) -> None:
        """Passing None for a nullable param clears it instead of sending the default."""
        http = _http(nullable_bodies.delay(item=Item(name="chili"), note=None))
        assert json.loads(http.body) == {"item": {"name": "chili"}, "note": None}

    def test_omitted_nullable_param_sends_its_default(self) -> None:
        """Leaving the argument out is still different from passing None."""
        http = _http(nullable_bodies.delay(item=Item(name="chili")))
        assert json.loads(http.body) == {"item": {"name": "chili"}, "note": "keep"}
        assert _replay(http) == (200, {"item": "chili", "note": "keep"})

    def test_required_nullable_param_accepts_none(self) -> None:
        """None is a real value for a required nullable param, not a missing argument."""
        http = _http(required_nullable_body.delay(item=Item(name="chili"), note=None))
        assert json.loads(http.body) == {"item": {"name": "chili"}, "note": None}

    def test_none_for_a_non_nullable_body_still_means_not_provided(self) -> None:
        """A param that cannot be null keeps the old meaning of None."""
        with pytest.raises(MissingParamError, match="item"):
            one_body.delay(item=None)  # type: ignore[arg-type]

    def test_non_finite_floats_reach_the_worker(self) -> None:
        """Infinity must not be rewritten to null, which the worker would reject."""
        http = _http(limits.delay(limits=Limits(limit=float("inf"))))
        assert _replay(http) == (200, {"is_inf": True})

    def test_model_body_matches_the_previous_encoding(self) -> None:
        """Model bodies stay byte-identical, so existing scheduled jobs are not seen as changed."""
        person = Aliased(fullName="Kevin Malone")
        http = _http(aliased_body.delay(person=person))
        assert bytes(http.body) == json.dumps(jsonable_encoder(person)).encode()


def test_optional_query_param_model_is_expanded() -> None:
    """``Filters | None`` is still a parameter model and must be expanded, not stringified."""

    class Filters(BaseModel):
        limit: int = 10
        tag: str | None = None

    model_router = APIRouter(
        route_class=DelayedRouteBuilder(
            client=client,
            callback_base_url="https://worker.example.com",
            queue_path=QUEUE_PATH,
            auto_create_queue=False,
        )
    )
    try:

        @model_router.post("/maybe_filtered")
        @as_delayed_task
        def maybe_filtered(filters: Annotated[Filters | None, Query()] = None) -> None:
            """Task with an optional query-parameter model."""

    except AssertionError:
        pytest.skip("this FastAPI version does not support optional parameter models")

    assert _query(_http(maybe_filtered.delay(filters=Filters(limit=5)))) == [("limit", "5")]
    assert _query(_http(maybe_filtered.delay())) == []
