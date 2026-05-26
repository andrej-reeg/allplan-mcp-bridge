"""Loopback TCP transport (fallback when named pipes are unavailable)."""

import hmac

import anyio
import anyio.abc

from .transport import AuthError, TransportClosedError, TransportError, _receive_exactly


class _RawStreamAdapter:
    """Wrap a raw anyio ByteStream to expose receive_exactly (needed by decode_stream)."""

    __slots__ = ("_stream",)

    def __init__(self, stream: anyio.abc.ByteStream) -> None:
        self._stream = stream

    async def receive_exactly(self, n: int) -> bytes:
        return await _receive_exactly(self._stream, n)


class TcpTransport:
    """Client-side loopback TCP transport with token auth.

    The server (agent side) sends ``{"hello": "<token>"}`` as the first frame
    upon accepting a connection. This client verifies that token before any
    real messages are exchanged.

    Never binds or connects to anything other than 127.0.0.1.
    """

    def __init__(self, host: str, port: int, token: str) -> None:
        if host != "127.0.0.1":
            raise ValueError(f"TcpTransport only allows 127.0.0.1, got {host!r}")
        self._host = host
        self._port = port
        self._token = token
        self._stream: anyio.abc.ByteStream | None = None

    @property
    def is_connected(self) -> bool:
        return self._stream is not None

    async def connect(self) -> None:
        from .framing import decode_stream, encode

        stream = await anyio.connect_tcp(self._host, self._port)
        # Expect the hello frame from the agent before anything else.
        # Use an adapter because the raw anyio stream lacks receive_exactly.
        frames = decode_stream(_RawStreamAdapter(stream))
        try:
            hello = await frames.__anext__()
        except StopAsyncIteration:
            await stream.aclose()
            raise TransportError("Agent closed connection before sending hello frame") from None

        received_token = hello.get("hello", "")
        if not isinstance(received_token, str) or not hmac.compare_digest(
            received_token, self._token
        ):
            await stream.aclose()
            raise AuthError("TCP hello token mismatch")

        # Send ack so agent knows auth succeeded
        await stream.send(encode({"ack": True}))
        self._stream = stream

    async def send(self, data: bytes) -> None:
        if self._stream is None:
            raise TransportClosedError("Not connected")
        await self._stream.send(data)

    async def receive_exactly(self, n: int) -> bytes:
        if self._stream is None:
            raise TransportClosedError("Not connected")
        return await _receive_exactly(self._stream, n)

    async def close(self) -> None:
        if self._stream is not None:
            await self._stream.aclose()
            self._stream = None
