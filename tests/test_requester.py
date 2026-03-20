"""Unit tests for Requester._body covering missing-param and generic-type bugs."""

# Standard Library Imports
from typing import List

# Third Party Imports
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from pydantic import BaseModel

# Imports from this repository
from fastapi_gcp_tasks.exception import MissingParamError, WrongTypeError
from fastapi_gcp_tasks.requester import Requester


class Item(BaseModel):
    """Simple model for testing."""

    name: str


app = FastAPI()


@app.post("/required_body")
async def required_body_endpoint(item: Item) -> None:
    """Endpoint with a required body param."""


@app.post("/optional_body")
async def optional_body_endpoint(item: Item = Item(name="default")) -> None:
    """Endpoint with an optional body param."""


@app.post("/list_body")
async def list_body_endpoint(items: List[Item]) -> None:
    """Endpoint with a parameterized generic body."""


def _get_route(path: str) -> APIRoute:
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path == path:
            return route
    raise ValueError(f"Route {path} not found")


class TestMissingRequiredBody:
    """Bug: MissingParamError called with name= but template expects {param}."""

    def test_missing_required_body_raises_missing_param_error(self) -> None:
        """Missing required body should raise MissingParamError, not KeyError."""
        route = _get_route("/required_body")
        requester = Requester(route=route, base_url="http://localhost")
        with pytest.raises(MissingParamError, match="field required"):
            requester._body(values={})

    def test_optional_body_uses_default(self) -> None:
        """Optional body should fall back to default when not provided."""
        route = _get_route("/optional_body")
        requester = Requester(route=route, base_url="http://localhost")
        body = requester._body(values={})
        assert body is not None
        assert b"default" in body


class TestGenericBodyType:
    """Bug: isinstance crashes with parameterized generics like list[Item]."""

    def test_list_body_does_not_crash_with_valid_input(self) -> None:
        """Parameterized generic body should not raise TypeError on isinstance."""
        route = _get_route("/list_body")
        requester = Requester(route=route, base_url="http://localhost")
        items = [Item(name="a"), Item(name="b")]
        body = requester._body(values={"items": items})
        assert body is not None

    def test_list_body_wrong_type_raises(self) -> None:
        """Wrong type for a generic body should raise WrongTypeError."""
        route = _get_route("/list_body")
        requester = Requester(route=route, base_url="http://localhost")
        with pytest.raises(WrongTypeError):
            requester._body(values={"items": "not a list"})

    def test_simple_body_wrong_type_raises(self) -> None:
        """Wrong type for a simple body should raise WrongTypeError."""
        route = _get_route("/required_body")
        requester = Requester(route=route, base_url="http://localhost")
        with pytest.raises(WrongTypeError):
            requester._body(values={"item": "not an Item"})
