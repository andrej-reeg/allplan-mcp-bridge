"""TCP server that acts as the Allplan agent in integration tests.

Implements the same IPC protocol as the real listener (hello/ack auth, then
length-prefixed JSON command/response loop) but dispatches via the real
`allplan_agent.dispatcher.dispatch` backed by `fake_allplan_api`.
"""

import asyncio
import json
import logging
import socket as _socket
import struct
from typing import Any

import anyio
import anyio.abc

# Import all handler modules to populate the dispatcher registry.
import allplan_agent.handlers.attributes  # noqa: F401
import allplan_agent.handlers.document  # noqa: F401
import allplan_agent.handlers.geometry  # noqa: F401
import allplan_agent.handlers.ifc  # noqa: F401
import allplan_agent.handlers.layers  # noqa: F401
from allplan_agent.dispatcher import dispatch
from allplan_mcp_server.ipc.framing import encode
from allplan_mcp_server.ipc.transport import _receive_exactly

_log = logging.getLogger(__name__)

_HEADER = struct.Struct(">I")
_MAX_FRAME = 16 * 1024 * 1024


class _StreamAdapter:
    """Wrap an anyio ByteStream to provide the `receive_exactly` method."""

    def __init__(self, stream: anyio.abc.ByteStream) -> None:
        self._s = stream

    async def receive_exactly(self, n: int) -> bytes:
        return await _receive_exactly(self._s, n)


async def _read_frame(adapter: _StreamAdapter) -> dict[str, Any] | None:
    """Return next decoded frame, or None on EOF / oversized frame."""
    try:
        header = await adapter.receive_exactly(_HEADER.size)
    except anyio.EndOfStream:
        return None
    (length,) = _HEADER.unpack(header)
    if length > _MAX_FRAME:
        return None
    try:
        payload = await adapter.receive_exactly(length)
    except anyio.EndOfStream:
        return None
    try:
        return json.loads(payload.decode())  # type: ignore[no-any-return]
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


async def _handle_connection(
    stream: anyio.abc.SocketStream, token: str
) -> None:
    adapter = _StreamAdapter(stream)

    # Auth handshake: server sends hello, client sends ack.
    await stream.send(encode({"hello": token}))
    ack = await _read_frame(adapter)
    if not ack or not ack.get("ack"):
        return

    # Command loop.
    while True:
        msg = await _read_frame(adapter)
        if msg is None:
            break

        req_id = msg.get("id", "")
        cmd = str(msg.get("cmd", ""))
        args: dict[str, Any] = msg.get("args") or {}

        try:
            result = dispatch(cmd, args)
            response: dict[str, Any] = {"id": req_id, "ok": True, "result": result}
        except KeyError as exc:
            response = {
                "id": req_id,
                "ok": False,
                "error": {"code": "NotFound", "message": str(exc)},
            }
        except Exception as exc:
            response = {
                "id": req_id,
                "ok": False,
                "error": {"code": "Internal", "message": str(exc)},
            }

        await stream.send(encode(response))


class FakeAgent:
    """Minimal TCP server acting as the Allplan agent for integration tests."""

    def __init__(self, token: str = "integration-test-token") -> None:
        self.token = token
        self.port: int = 0

    async def serve(
        self, *, task_status: anyio.abc.TaskStatus[int] = anyio.TASK_STATUS_IGNORED
    ) -> None:
        """Start listening. Reports port via task_status.started()."""
        # Reserve a free port before anyio binds so we can report it.
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        self.port = port
        token = self.token

        async def _handler(stream: anyio.abc.SocketStream) -> None:
            async with stream:
                await _handle_connection(stream, token)

        listener = await anyio.create_tcp_listener(
            local_host="127.0.0.1", local_port=port
        )
        task_status.started(port)
        _log.info("fake_agent.listening port=%d", port)
        async with listener:
            await listener.serve(_handler)

    async def serve_asyncio(self, started: asyncio.Event) -> None:
        """asyncio-compatible serve for pytest-asyncio fixtures.

        Avoids anyio cancel scopes crossing task boundaries.
        Sets `started` once the listener is bound and ready, then serves until cancelled.
        """
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]

        token = self.token

        async def _handler(stream: anyio.abc.SocketStream) -> None:
            async with stream:
                await _handle_connection(stream, token)

        listener = await anyio.create_tcp_listener(
            local_host="127.0.0.1", local_port=self.port
        )
        started.set()
        _log.info("fake_agent.listening port=%d", self.port)
        try:
            async with listener:
                await listener.serve(_handler)
        except asyncio.CancelledError:
            pass
