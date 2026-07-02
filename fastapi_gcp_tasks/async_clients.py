# Standard Library Imports
import asyncio
from collections.abc import Callable
from typing import Generic, TypeVar

ClientT = TypeVar("ClientT")


class AsyncClientProvider(Generic[ClientT]):
    """
    Lazily resolves and caches an async gRPC client inside the running event loop.

    grpc.aio channels bind to the event loop active at construction, so the client
    (or client factory) is only resolved on first use, from within the loop that
    will await the RPCs. One provider should be shared per route builder so all
    calls reuse the same client and channel.
    """

    def __init__(
        self,
        *,
        client: "ClientT | Callable[[], ClientT] | None",
        client_cls: type[ClientT],
    ) -> None:
        self._client_or_factory = client
        self._client_cls = client_cls
        self._client: ClientT | None = None
        self._lock = asyncio.Lock()

    async def get(self) -> ClientT:
        """Return the cached client, resolving it on first call."""
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                self._client = self._resolve()
            return self._client

    def _resolve(self) -> ClientT:
        client = self._client_or_factory
        if client is None:
            return self._client_cls()
        if isinstance(client, self._client_cls):
            return client
        if callable(client):
            resolved = client()
            if not isinstance(resolved, self._client_cls):
                raise TypeError(
                    f"client factory must return a {self._client_cls.__name__}; got {type(resolved).__name__}"
                )
            return resolved
        raise TypeError(
            f"client must be a {self._client_cls.__name__}, a zero-argument factory returning one, or None; "
            f"got {type(client).__name__}"
        )
