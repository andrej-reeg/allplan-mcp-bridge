"""Background listener thread: accepts IPC connections and enqueues commands.

THREADING CONTRACT:
  - This module MUST NOT import anything from allplan_agent/handlers/_allplan.py.
  - It does I/O and enqueues Commands only.
  - All Allplan API calls happen in pump_once() on the main thread.
"""

import json
import logging
import socket
import struct
import threading
import time
from concurrent.futures import Future
from typing import Any

from .command_queue import Command, CommandQueue, QueueFullError

_log = logging.getLogger(__name__)

_HEADER = struct.Struct(">I")
_MAX_FRAME = 16 * 1024 * 1024
_HEARTBEAT_INTERVAL = 5.0  # seconds


def _send_frame(sock: socket.socket, obj: dict[str, Any]) -> None:
    payload = json.dumps(obj, separators=(",", ":")).encode()
    sock.sendall(_HEADER.pack(len(payload)) + payload)


def _recv_frame(sock: socket.socket) -> dict[str, Any] | None:
    """Read one length-prefixed frame. Returns None on EOF."""
    try:
        header = _recv_exactly(sock, _HEADER.size)
    except (OSError, EOFError):
        return None
    if header is None:
        return None
    (length,) = _HEADER.unpack(header)
    if length > _MAX_FRAME:
        _log.warning("listener.frame_too_large length=%d", length)
        return None
    payload = _recv_exactly(sock, length)
    if payload is None:
        return None
    try:
        return dict(json.loads(payload.decode()))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _recv_exactly(sock: socket.socket, n: int) -> bytes | None:
    buf = bytearray()
    remaining = n
    while remaining > 0:
        try:
            chunk = sock.recv(remaining)
        except OSError:
            return None
        if not chunk:
            return None
        buf.extend(chunk)
        remaining -= len(chunk)
    return bytes(buf)


def _handle_connection(
    conn: socket.socket,
    q: CommandQueue,
    request_timeout: float,
) -> None:
    """Serve one client connection until it closes."""
    pending: dict[str, Future[dict[str, Any]]] = {}

    def _heartbeat_loop() -> None:
        while True:
            try:
                _send_frame(conn, {"event": "heartbeat", "ts": time.time()})
                time.sleep(_HEARTBEAT_INTERVAL)
            except OSError:
                break

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb_thread.start()

    try:
        while True:
            msg = _recv_frame(conn)
            if msg is None:
                break

            req_id = msg.get("id")
            cmd_name = msg.get("cmd")
            args = msg.get("args", {})
            deadline_ms = msg.get("deadline_ms", int(request_timeout * 1000))

            if not isinstance(req_id, str) or not isinstance(cmd_name, str):
                continue
            if not isinstance(args, dict):
                args = {}

            timeout_s = deadline_ms / 1000.0

            fut: Future[dict[str, Any]] = Future()
            cmd = Command(
                id=req_id,
                cmd_name=cmd_name,
                args=args,
                future=fut,
                deadline_at=time.monotonic() + timeout_s,
            )

            try:
                q.enqueue(cmd)
            except QueueFullError:
                _send_frame(conn, {
                    "id": req_id,
                    "ok": False,
                    "error": {"code": "Internal", "message": "Command queue full"},
                })
                continue

            pending[req_id] = fut

            t0 = time.monotonic()
            try:
                result = fut.result(timeout=timeout_s + 1.0)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                _send_frame(conn, {
                    "id": req_id, "ok": True, "result": result, "elapsed_ms": elapsed_ms,
                })
            except TimeoutError:
                _send_frame(conn, {
                    "id": req_id,
                    "ok": False,
                    "error": {"code": "Timeout", "message": f"No result for {cmd_name!r}"},
                })
            except Exception as exc:
                _send_frame(conn, {
                    "id": req_id,
                    "ok": False,
                    "error": {"code": "AllplanApiError", "message": str(exc)},
                })
            finally:
                pending.pop(req_id, None)
    finally:
        conn.close()


class TcpListenerThread(threading.Thread):
    """Listens on a loopback TCP port, spawns a handler per connection."""

    def __init__(
        self,
        q: CommandQueue,
        host: str = "127.0.0.1",
        port: int = 0,
        request_timeout: float = 10.0,
    ) -> None:
        super().__init__(daemon=True, name="allplan-ipc-listener")
        self._q = q
        self._host = host
        self._port = port
        self._request_timeout = request_timeout
        self._server: socket.socket | None = None
        self._actual_port: int = 0
        self._stop_event = threading.Event()

    @property
    def actual_port(self) -> int:
        return self._actual_port

    def run(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self._host, self._port))
        server.listen(4)
        self._server = server
        self._actual_port = server.getsockname()[1]
        _log.info("listener.started host=%s port=%d", self._host, self._actual_port)

        server.settimeout(1.0)
        while not self._stop_event.is_set():
            try:
                conn, addr = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            _log.info("listener.connection addr=%s", addr)
            t = threading.Thread(
                target=_handle_connection,
                args=(conn, self._q, self._request_timeout),
                daemon=True,
            )
            t.start()

        server.close()

    def stop(self) -> None:
        self._stop_event.set()
        if self._server is not None:
            import contextlib
            with contextlib.suppress(OSError):
                self._server.close()
