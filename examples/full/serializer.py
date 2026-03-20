# Third Party Imports
from pydantic import BaseModel


class Payload(BaseModel):
    """Basic payload from the api."""

    message: str
