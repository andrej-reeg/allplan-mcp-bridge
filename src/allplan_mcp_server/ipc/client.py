"""IPC client: request/response correlator with timeout and auto-reconnect."""

import asyncio
import time
import uuid
from collections.abc import Callable
from typing import Any

import anyio
import structlog

from .framing import decode_stream, encode
from .transport import Transport, TransportError

log = structlog.get_logger(__name__)

_RECONNECT_BASE = 0.1  # seconds
_RECONNECT_CAP = 5.0  # seconds


class IpcError(Exception):
    """Base for IPC-level errors returned from the agent."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class IpcClient:
    """Maintains one IPC connection; correlates requests to responses by id.

    Usage::

        client = IpcClient(transport_factory)
        await client.start()
        result = await client.call("create_wall", {"start": ...}, timeout=10.0)
        await client.stop()

    Auto-reconnects with exponential backoff (capped at 5 s). In-flight futures
    resolve with ``IpcError(code="AgentDisconnected")`` on disconnect.
    """

    def __init__(self, transport_factory: Callable[[], Transport]) -> None:
        self._factory = transport_factory
        self._transport: Transport | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._running = False
        self._last_heartbeat_at: float = time.monotonic()
        self._reconnect_count = 0
        self._send_lock = asyncio.Lock()  # serialise concurrent sends on one stream

    @property
    def is_connected(self) -> bool:
        return self._transport is not None and self._transport.is_connected

    async def start(self) -> None:
        self._running = True
        await self._connect_once()

    async def stop(self) -> None:
        self._running = False
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
        self._fail_all_pending("AgentDisconnected", "Client stopped")
        if self._transport is not None:
            await self._transport.close()

    async def call(
        self,
        cmd: str,
        args: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Send a command and await the response.

        Raises ``IpcError`` on agent-reported errors, timeouts, or disconnect.
        """
        if not self.is_connected:
            raise IpcError("AgentDisconnected", "Not connected to agent")

        req_id = str(uuid.uuid4())
        deadline_ms = int(timeout * 1000)
        frame = encode({"id": req_id, "cmd": cmd, "args": args, "deadline_ms": deadline_ms})

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = fut

        try:
            assert self._transport is not None
            async with self._send_lock:
                await self._transport.send(frame)
        except Exception as exc:
            self._pending.pop(req_id, None)
            raise IpcError("AgentDisconnected", f"Send failed: {exc}") from exc

        try:
            response = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except TimeoutError:
            self._pending.pop(req_id, None)
            raise IpcError("Timeout", f"No response within {timeout}s for cmd={cmd!r}") from None

        if not response.get("ok"):
            err = response.get("error", {})
            raise IpcError(
                err.get("code", "Internal"),
                err.get("message", "Unknown error"),
                err.get("details"),
            )

        return dict(response.get("result") or {})

    # --- internal ---

    async def _connect_once(self) -> None:
        transport = self._factory()
        try:
            await transport.connect()
        except TransportError as exc:
            log.warning("ipc.connect_failed", error=str(exc))
            asyncio.get_running_loop().create_task(self._reconnect_loop())
            return
        self._transport = transport
        self._last_heartbeat_at = time.monotonic()
        self._reader_task = asyncio.get_running_loop().create_task(self._reader_loop())
        log.info("ipc.connected")

    async def _reader_loop(self) -> None:
        assert self._transport is not None
        try:
            async for msg in decode_stream(self._transport):
                self._dispatch(msg)
        finally:
            self._on_disconnect()

    def _dispatch(self, msg: dict[str, Any]) -> None:
        if msg.get("event") == "heartbeat":
            self._last_heartbeat_at = time.monotonic()
            return

        req_id = msg.get("id")
        if isinstance(req_id, str):
            fut = self._pending.pop(req_id, None)
            if fut is not None and not fut.done():
                fut.set_result(msg)

    def _on_disconnect(self) -> None:
        self._transport = None
        self._fail_all_pending("AgentDisconnected", "Connection lost")
        if self._running:
            asyncio.get_running_loop().create_task(self._reconnect_loop())

    def _fail_all_pending(self, code: str, message: str) -> None:
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(IpcError(code, message))
        self._pending.clear()

    async def _reconnect_loop(self) -> None:
        delay = _RECONNECT_BASE
        while self._running and not self.is_connected:
            await anyio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_CAP)
            self._reconnect_count += 1
            log.info("ipc.reconnecting", attempt=self._reconnect_count)
            await self._connect_once()
