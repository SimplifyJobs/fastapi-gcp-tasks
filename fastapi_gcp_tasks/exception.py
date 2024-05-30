# Third Party Imports
from pydantic.v1.errors import MissingError, PydanticValueError

# TODO: Migrate to Pydantic v2.0 Errors


class MissingParamError(MissingError):
    """Error raised when a required parameter is missing."""

    msg_template = "field required: {param}"


class WrongTypeError(PydanticValueError):
    """Error raised when a parameter is of the wrong type."""

    msg_template = "Expected {field} to be of type {type}"


class BadMethodError(Exception):
    """Error raised when an invalid method is passed to a task."""

    pass
