"""Tests for ipc/client.py using a fake in-memory transport."""

import asyncio
import struct
import time
from typing import Any

import pytest

from allplan_mcp_server.ipc.client import IpcClient, IpcError
from allplan_mcp_server.ipc.framing import encode
from allplan_mcp_server.ipc.transport import TransportError


class FakeTransport:
    """In-memory transport: server side enqueues raw frames, client reads them."""

    def __init__(self) -> None:
        self._send_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._recv_buf = bytearray()
        self._recv_event = asyncio.Event()
        self._connected = False
        self._fail_on_connect = False
        self._fail_on_send = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        if self._fail_on_connect:
            raise TransportError("Simulated connect failure")
        self._connected = True

    async def send(self, data: bytes) -> None:
        if self._fail_on_send:
            raise TransportError("Simulated send failure")
        await self._send_queue.put(data)

    async def receive_exactly(self, n: int) -> bytes:
        import anyio

        while len(self._recv_buf) < n:
            if not self._connected:
                raise anyio.EndOfStream
            self._recv_event.clear()
            await self._recv_event.wait()
            if not self._connected and len(self._recv_buf) < n:
                raise anyio.EndOfStream
        chunk = bytes(self._recv_buf[:n])
        del self._recv_buf[:n]
        return chunk

    async def close(self) -> None:
        self._connected = False
        self._recv_event.set()  # wake any blocked receive_exactly

    def inject(self, frame: bytes) -> None:
        """Push raw bytes into the receive buffer (simulates agent sending)."""
        self._recv_buf.extend(frame)
        self._recv_event.set()

    def inject_obj(self, obj: dict[str, Any]) -> None:
        self.inject(encode(obj))

    async def get_sent(self, timeout: float = 1.0) -> dict[str, Any]:
        """Pop the next frame the client sent and decode it."""
        import json

        raw = await asyncio.wait_for(self._send_queue.get(), timeout=timeout)
        (length,) = struct.unpack(">I", raw[:4])
        return dict(json.loads(raw[4 : 4 + length]))  # type: ignore[arg-type]


@pytest.fixture
def transport() -> FakeTransport:
    return FakeTransport()


@pytest.fixture
def client(transport: FakeTransport) -> IpcClient:
    return IpcClient(lambda: transport)


@pytest.mark.anyio
async def test_call_success(transport: FakeTransport, client: IpcClient) -> None:
    await client.start()
    assert client.is_connected

    async def _serve() -> None:
        req = await transport.get_sent()
        transport.inject_obj(
            {"id": req["id"], "ok": True, "result": {"uuid": "w1"}, "elapsed_ms": 5}
        )

    task = asyncio.create_task(_serve())
    result = await client.call("create_wall", {}, timeout=2.0)
    await task
    assert result == {"uuid": "w1"}
    await client.stop()


@pytest.mark.anyio
async def test_call_agent_error(transport: FakeTransport, client: IpcClient) -> None:
    await client.start()

    async def _serve() -> None:
        req = await transport.get_sent()
        transport.inject_obj({
            "id": req["id"],
            "ok": False,
            "error": {"code": "NotFound", "message": "No such element"},
        })

    task = asyncio.create_task(_serve())
    with pytest.raises(IpcError) as exc_info:
        await client.call("get_element", {"id": "missing"}, timeout=2.0)
    await task
    assert exc_info.value.code == "NotFound"
    await client.stop()


@pytest.mark.anyio
async def test_call_timeout(transport: FakeTransport, client: IpcClient) -> None:
    await client.start()
    # Never respond — let the timeout fire
    with pytest.raises(IpcError) as exc_info:
        await client.call("slow_op", {}, timeout=0.05)
    assert exc_info.value.code == "Timeout"
    await client.stop()


@pytest.mark.anyio
async def test_late_response_is_dropped(transport: FakeTransport, client: IpcClient) -> None:
    """Response arriving after timeout must not crash the reader loop."""
    await client.start()
    req_task: asyncio.Task[dict[str, Any]] | None = None

    async def _serve() -> None:
        req = await transport.get_sent()
        await asyncio.sleep(0.15)  # arrives after 0.05s timeout
        transport.inject_obj({"id": req["id"], "ok": True, "result": {}, "elapsed_ms": 150})

    req_task = asyncio.create_task(_serve())
    with pytest.raises(IpcError) as exc_info:
        await client.call("slow_op", {}, timeout=0.05)
    assert exc_info.value.code == "Timeout"
    await req_task
    # Client still healthy — another call should work
    assert client.is_connected
    await client.stop()


@pytest.mark.anyio
async def test_concurrent_calls_correlate(transport: FakeTransport, client: IpcClient) -> None:
    await client.start()

    reqs: list[dict[str, Any]] = []

    async def _collect_and_respond(n: int) -> None:
        for _ in range(n):
            req = await transport.get_sent()
            reqs.append(req)
        # Respond in reverse order to verify correlation
        for req in reversed(reqs):
            transport.inject_obj(
                {"id": req["id"], "ok": True, "result": {"id": req["id"]}, "elapsed_ms": 1}
            )

    n = 10
    server_task = asyncio.create_task(_collect_and_respond(n))
    results = await asyncio.gather(
        *[client.call(f"cmd_{i}", {}, timeout=2.0) for i in range(n)]
    )
    await server_task

    returned_ids = {r["id"] for r in results}
    sent_ids = {r["id"] for r in reqs}
    assert returned_ids == sent_ids
    await client.stop()


@pytest.mark.anyio
async def test_disconnect_fails_pending(transport: FakeTransport, client: IpcClient) -> None:
    await client.start()

    async def _close_without_responding() -> None:
        await transport.get_sent()  # consume the request
        transport._connected = False
        transport._recv_event.set()  # unblock reader

    server_task = asyncio.create_task(_close_without_responding())
    with pytest.raises(IpcError) as exc_info:
        await client.call("any", {}, timeout=2.0)
    await server_task
    assert exc_info.value.code == "AgentDisconnected"
    await client.stop()


@pytest.mark.anyio
async def test_heartbeat_updates_timestamp(transport: FakeTransport, client: IpcClient) -> None:
    await client.start()
    before = client._last_heartbeat_at
    await asyncio.sleep(0.01)
    transport.inject_obj({"event": "heartbeat", "ts": time.time()})
    await asyncio.sleep(0.05)  # let reader task process it
    assert client._last_heartbeat_at >= before
    await client.stop()


@pytest.mark.anyio
async def test_call_fails_when_not_connected(transport: FakeTransport, client: IpcClient) -> None:
    # Never call start()
    with pytest.raises(IpcError) as exc_info:
        await client.call("ping", {}, timeout=1.0)
    assert exc_info.value.code == "AgentDisconnected"
