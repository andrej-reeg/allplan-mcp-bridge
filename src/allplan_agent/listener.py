"""Background listener thread: accepts IPC connections and enqueues commands.

THREADING CONTRACT:
  - This module MUST NOT import anything from allplan_agent/handlers/_allplan.py.
  - It does I/O and enqueues Commands only.
  - All Allplan API calls happen in pump_once() on the main thread.
"""

import contextlib
import json
import logging
import socket
import struct
import sys
import threading
import time
from concurrent.futures import Future
from typing import Any, Protocol, runtime_checkable

from .command_queue import Command, CommandQueue, QueueFullError

_log = logging.getLogger(__name__)

_HEADER = struct.Struct(">I")
_MAX_FRAME = 16 * 1024 * 1024
_HEARTBEAT_INTERVAL = 5.0  # seconds


@runtime_checkable
class _SocketLike(Protocol):
    def recv(self, n: int) -> bytes: ...
    def sendall(self, data: bytes) -> None: ...
    def close(self) -> None: ...


class _NamedPipeSocket:
    """Wraps a Windows named pipe handle to implement the _SocketLike protocol."""

    def __init__(self, handle: Any) -> None:
        self._handle = handle

    def recv(self, n: int) -> bytes:
        import win32file  # type: ignore[import-untyped]
        hr, data = win32file.ReadFile(self._handle, n)
        if hr != 0:
            raise OSError(f"ReadFile failed with code {hr}")
        return bytes(data)

    def sendall(self, data: bytes) -> None:
        import win32file
        hr, _written = win32file.WriteFile(self._handle, data)
        if hr != 0:
            raise OSError(f"WriteFile failed with code {hr}")

    def close(self) -> None:
        try:
            import win32file
            import win32pipe  # type: ignore[import-untyped]
            win32pipe.DisconnectNamedPipe(self._handle)
            win32file.CloseHandle(self._handle)
        except Exception:
            pass


def _send_frame(sock: _SocketLike, obj: dict[str, Any]) -> None:
    payload = json.dumps(obj, separators=(",", ":")).encode()
    sock.sendall(_HEADER.pack(len(payload)) + payload)


def _recv_frame(sock: _SocketLike) -> dict[str, Any] | None:
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


def _recv_exactly(sock: _SocketLike, n: int) -> bytes | None:
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
    conn: "_SocketLike",
    q: CommandQueue,
    request_timeout: float,
) -> None:
    """Serve one client connection until it closes."""
    pending: dict[str, Future[dict[str, Any]]] = {}

    def _heartbeat_loop() -> None:
        while True:
            try:
                _send_frame(conn, {
                    "event": "heartbeat",
                    "ts": time.time(),
                    "queue_depth": q.size,
                })
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
            # correlation_id propagated from server; falls back to req_id
            correlation_id = msg.get("correlation_id") or req_id

            if not isinstance(req_id, str) or not isinstance(cmd_name, str):
                continue
            if not isinstance(args, dict):
                args = {}

            timeout_s = deadline_ms / 1000.0

            _log.debug(
                "listener.request correlation_id=%s cmd=%s", correlation_id, cmd_name
            )

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
                    "correlation_id": correlation_id,
                    "error": {"code": "Internal", "message": "Command queue full"},
                })
                continue

            pending[req_id] = fut

            t0 = time.monotonic()
            try:
                result = fut.result(timeout=timeout_s + 1.0)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                _send_frame(conn, {
                    "id": req_id,
                    "ok": True,
                    "result": result,
                    "elapsed_ms": elapsed_ms,
                    "correlation_id": correlation_id,
                })
            except TimeoutError:
                _send_frame(conn, {
                    "id": req_id,
                    "ok": False,
                    "correlation_id": correlation_id,
                    "error": {"code": "Timeout", "message": f"No result for {cmd_name!r}"},
                })
            except Exception as exc:
                _send_frame(conn, {
                    "id": req_id,
                    "ok": False,
                    "correlation_id": correlation_id,
                    "error": {"code": "AllplanApiError", "message": str(exc)},
                })
            finally:
                pending.pop(req_id, None)
    finally:
        conn.close()


def _serve_tcp_conn(
    conn: socket.socket,
    q: CommandQueue,
    request_timeout: float,
    token: str,
) -> None:
    """Send hello frame then serve one TCP connection."""
    try:
        _send_frame(conn, {"hello": token})
    except OSError as exc:
        _log.warning("listener.hello_failed error=%s", exc)
        conn.close()
        return
    _handle_connection(conn, q, request_timeout)


class TcpListenerThread(threading.Thread):
    """Listens on a TCP port, spawns a handler per connection.

    On Windows the bridge typically uses NamedPipeListenerThread; this thread
    is used on non-Windows platforms and when force_tcp=True is set in config
    to allow cross-network clients (e.g. WSL2 → Windows).
    """

    def __init__(
        self,
        q: CommandQueue,
        host: str = "127.0.0.1",
        port: int = 0,
        request_timeout: float = 10.0,
        token: str = "",
    ) -> None:
        super().__init__(daemon=True, name="allplan-ipc-listener")
        self._q = q
        self._host = host
        self._port = port
        self._request_timeout = request_timeout
        self._token = token
        self._server: socket.socket | None = None
        self._actual_port: int = 0
        self._stop_event = threading.Event()
        self._active_conns: list[socket.socket] = []
        self._conns_lock = threading.Lock()

    @property
    def actual_port(self) -> int:
        return self._actual_port

    def _serve_and_track(self, conn: socket.socket) -> None:
        """Serve one connection, removing it from tracking when done."""
        try:
            _serve_tcp_conn(conn, self._q, self._request_timeout, self._token)
        finally:
            with self._conns_lock, contextlib.suppress(ValueError):
                self._active_conns.remove(conn)

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
            with self._conns_lock:
                self._active_conns.append(conn)
            t = threading.Thread(
                target=self._serve_and_track,
                args=(conn,),
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
        # Close active client connections so MCP server detects disconnect
        # and reconnects to the new bridge instance.
        with self._conns_lock:
            for conn in list(self._active_conns):
                import contextlib
                with contextlib.suppress(OSError):
                    conn.close()
            self._active_conns.clear()


class NamedPipeListenerThread(threading.Thread):
    """Listens on a Windows named pipe, spawns a handler per connection."""

    def __init__(
        self,
        q: CommandQueue,
        pipe_name: str,
        request_timeout: float = 10.0,
    ) -> None:
        super().__init__(daemon=True, name="allplan-pipe-listener")
        self._q = q
        self._pipe_name = pipe_name
        self._request_timeout = request_timeout
        self._stop_event = threading.Event()

    def run(self) -> None:
        if sys.platform != "win32":
            _log.error("pipe.listener_platform_unsupported platform=%s", sys.platform)
            return

        try:
            import win32file
            import win32pipe
            import win32security  # type: ignore[import-untyped]
        except ImportError:
            _log.error("pipe.listener_import_failed pywin32 not installed")
            return

        try:
            import win32api  # type: ignore[import-untyped]

            token = win32security.OpenProcessToken(
                win32security.GetCurrentProcess(),
                win32security.TOKEN_QUERY,
            )
            current_user_sid, _ = win32security.GetTokenInformation(
                token, win32security.TokenUser
            )
            dacl = win32security.ACL()
            dacl.AddAccessAllowedAce(
                win32security.ACL_REVISION,
                0x001F0000 | 0x00120089,
                current_user_sid,
            )
            sd = win32security.SECURITY_DESCRIPTOR()
            sd.SetSecurityDescriptorDacl(True, dacl, False)
            sa = win32security.SECURITY_ATTRIBUTES()
            sa.SECURITY_DESCRIPTOR = sd
        except Exception:
            _log.exception("pipe.listener_dacl_failed")
            return

        _log.info("pipe.listener_started name=%s", self._pipe_name)

        while not self._stop_event.is_set():
            try:
                pipe_handle = win32pipe.CreateNamedPipe(
                    self._pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_READMODE_BYTE | win32pipe.PIPE_WAIT,
                    1,
                    65536,
                    65536,
                    0,
                    sa,
                )
            except Exception:
                _log.exception("pipe.create_failed name=%s", self._pipe_name)
                time.sleep(1.0)
                continue

            try:
                win32pipe.ConnectNamedPipe(pipe_handle, None)
            except Exception:
                if win32api.GetLastError() != 535:  # ERROR_PIPE_CONNECTED
                    import contextlib
                    with contextlib.suppress(Exception):
                        win32file.CloseHandle(pipe_handle)
                    continue

            if self._stop_event.is_set():
                import contextlib
                with contextlib.suppress(Exception):
                    win32file.CloseHandle(pipe_handle)
                break

            pipe_sock = _NamedPipeSocket(pipe_handle)
            t = threading.Thread(
                target=_handle_connection,
                args=(pipe_sock, self._q, self._request_timeout),
                daemon=True,
            )
            t.start()
            _log.info("pipe.client_connected name=%s", self._pipe_name)

    def stop(self) -> None:
        self._stop_event.set()
