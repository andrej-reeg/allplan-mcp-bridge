"""Abstract transport interface for IPC."""

from typing import Any, Protocol, runtime_checkable

import anyio.abc


async def _receive_exactly(stream: anyio.abc.ByteReceiveStream, n: int) -> bytes:
    """Read exactly n bytes from an anyio receive stream via repeated receive() calls."""
    buf = bytearray()
    remaining = n
    while remaining > 0:
        chunk = await stream.receive(remaining)
        if not chunk:
            raise anyio.EndOfStream
        buf.extend(chunk)
        remaining -= len(chunk)
    return bytes(buf)


@runtime_checkable
class Transport(Protocol):
    async def connect(self) -> None: ...

    async def send(self, data: bytes) -> None: ...

    async def receive_exactly(self, n: int) -> bytes: ...

    async def close(self) -> None: ...

    @property
    def is_connected(self) -> bool: ...


class TransportError(Exception):
    """Raised when a transport operation fails unrecoverably."""


class TransportClosedError(TransportError):
    """Raised on read/write after the transport has been closed."""


class AuthError(TransportError):
    """Raised when TCP hello-token auth fails."""


def _check_connected(connected: bool) -> None:
    if not connected:
        raise TransportClosedError("Transport is not connected")


# Re-export for convenience
__all__: list[Any] = [
    "Transport",
    "TransportError",
    "TransportClosedError",
    "AuthError",
]
