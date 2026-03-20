class MissingParamError(ValueError):
    """Error raised when a required parameter is missing."""

    msg_template = "field required: {param}"

    def __init__(self, **ctx: object) -> None:
        super().__init__(self.msg_template.format(**ctx))


class WrongTypeError(ValueError):
    """Error raised when a parameter is of the wrong type."""

    msg_template = "Expected {field} to be of type {type}"

    def __init__(self, **ctx: object) -> None:
        super().__init__(self.msg_template.format(**ctx))


class BadMethodError(Exception):
    """Error raised when an invalid method is passed to a task."""

    pass
