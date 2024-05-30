# Third Party Imports
from pydantic.v1 import BaseModel


class Payload(BaseModel):
    """Basic payload from the api."""

    message: str
