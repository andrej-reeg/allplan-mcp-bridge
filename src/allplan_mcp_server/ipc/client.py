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

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}
        self.correlation_id = correlation_id or str(uuid.uuid4())

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()} [correlation_id: {self.correlation_id}]"


_DEFAULT_MAX_ARG_BYTES = 1024 * 1024  # 1 MiB


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

    def __init__(
        self,
        transport_factory: Callable[[], Transport],
        max_arg_bytes: int = _DEFAULT_MAX_ARG_BYTES,
    ) -> None:
        self._factory = transport_factory
        self._max_arg_bytes = max_arg_bytes
        self._transport: Transport | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._running = False
        self._last_heartbeat_at: float = time.monotonic()
        self._last_queue_depth: int = 0
        self._reconnect_count: int = 0
        self._send_lock = asyncio.Lock()  # serialise concurrent sends on one stream

    @property
    def is_connected(self) -> bool:
        return self._transport is not None and self._transport.is_connected

    async def start(self) -> None:
        self._running = True
        await self._connect_once()
        if not self.is_connected and self._running:
            asyncio.get_running_loop().create_task(self._reconnect_loop())

    async def stop(self) -> None:
        self._running = False
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
        self._fail_all_pending("AgentDisconnected", "Client stopped")
        if self._transport is not None:
            await self._transport.close()

    async def drain(self, timeout: float = 5.0) -> None:
        """Wait up to timeout seconds for in-flight calls to complete gracefully."""
        deadline = time.monotonic() + timeout
        while self._pending and time.monotonic() < deadline:
            await anyio.sleep(0.05)

    async def call(
        self,
        cmd: str,
        args: dict[str, Any],
        timeout: float,
    ) -> dict[str, Any]:
        """Send a command and await the response.

        Raises ``IpcError`` on agent-reported errors, timeouts, or disconnect.
        Raises ``IpcError("InvalidArgs", ...)`` if args exceed the size cap.

        Every call is assigned a ``correlation_id`` (= request UUID) that appears
        in both this server's logs and the agent's ``pump_once`` logs, making
        cross-process tracing possible by grepping for the same UUID.
        """
        if not self.is_connected:
            raise IpcError("AgentDisconnected", "Not connected to agent")

        # Guard against pathological inputs before they hit the wire.
        from ..security import ArgSizeTooLargeError, validate_arg_size

        try:
            validate_arg_size(args, self._max_arg_bytes)
        except ArgSizeTooLargeError as exc:
            raise IpcError("InvalidArgs", str(exc)) from exc

        req_id = str(uuid.uuid4())
        deadline_ms = int(timeout * 1000)
        frame = encode({
            "id": req_id,
            "cmd": cmd,
            "args": args,
            "deadline_ms": deadline_ms,
            "correlation_id": req_id,  # propagated to agent logs
        })

        loop = asyncio.get_running_loop()
        fut: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = fut

        log.debug("ipc.call_start", cmd=cmd, correlation_id=req_id)
        t0 = time.monotonic()
        _error = False

        try:
            assert self._transport is not None
            async with self._send_lock:
                await self._transport.send(frame)
        except Exception as exc:
            self._pending.pop(req_id, None)
            _error = True
            raise IpcError("AgentDisconnected", f"Send failed: {exc}") from exc
        finally:
            if _error:
                _record_metric(cmd, (time.monotonic() - t0) * 1000, error=True)

        try:
            response = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except TimeoutError:
            self._pending.pop(req_id, None)
            _record_metric(cmd, (time.monotonic() - t0) * 1000, error=True)
            raise IpcError("Timeout", f"No response within {timeout}s for cmd={cmd!r}") from None

        elapsed_ms = int((time.monotonic() - t0) * 1000)

        if not response.get("ok"):
            err = response.get("error", {})
            log.error(
                "ipc.agent_error",
                cmd=cmd,
                code=err.get("code"),
                message=err.get("message"),
                details=err.get("details"),
                correlation_id=req_id,
                elapsed_ms=elapsed_ms,
            )
            _record_metric(cmd, elapsed_ms, error=True)
            raise IpcError(
                err.get("code", "Internal"),
                err.get("message", "Unknown error"),
                err.get("details"),
                correlation_id=req_id,
            )

        log.debug("ipc.call_ok", cmd=cmd, correlation_id=req_id, elapsed_ms=elapsed_ms)
        _record_metric(cmd, elapsed_ms, error=False)
        return dict(response.get("result") or {})

    # --- internal ---

    async def _connect_once(self) -> None:
        transport = self._factory()
        try:
            await transport.connect()
        except TransportError as exc:
            log.warning("ipc.connect_failed", error=str(exc))
            return  # caller (_reconnect_loop or start) handles retry scheduling
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
            self._last_queue_depth = int(msg.get("queue_depth", 0))
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


def _record_metric(cmd: str, elapsed_ms: float, *, error: bool) -> None:
    try:
        from ..metrics import get_metrics
        get_metrics().record_call(cmd, elapsed_ms, error=error)
    except Exception:
        pass
