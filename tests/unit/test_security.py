"""Security hardening tests — Phase 7.

Covers: path traversal, UNC paths, symlink escape, arg size cap,
IFC size check, token auth (TCP), oversized frames, pathological inputs.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

import pytest

from allplan_mcp_server.security import (
    ArgSizeTooLargeError,
    PathNotAllowedError,
    check_ifc_export_size,
    validate_arg_size,
    validate_path,
)

# ---------------------------------------------------------------------------
# validate_path — path traversal
# ---------------------------------------------------------------------------


def test_validate_path_absolute_inside_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "model.ifc"
    target.touch()
    result = validate_path(target, workspace)
    assert result == target.resolve()


def test_validate_path_rejects_relative(tmp_path: Path) -> None:
    with pytest.raises(PathNotAllowedError, match="absolute"):
        validate_path(Path("relative/path.ifc"), tmp_path)


def test_validate_path_dot_dot_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evil = workspace / ".." / "etc" / "passwd"
    with pytest.raises(PathNotAllowedError, match="outside"):
        validate_path(evil, workspace)


def test_validate_path_etc_passwd(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(PathNotAllowedError, match="outside"):
        validate_path(Path("/etc/passwd"), workspace)


def test_validate_path_root_escape_via_dotdot_string(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    # Construct path that resolves outside via multiple ..
    evil = Path(str(workspace) + "/deep/../../.." + str(tmp_path) + "/../etc/passwd")
    with pytest.raises(PathNotAllowedError):
        validate_path(evil, workspace)


def test_validate_path_symlink_inside_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target_dir = workspace / "subdir"
    target_dir.mkdir()
    link = workspace / "link"
    link.symlink_to(target_dir)
    result = validate_path(link / "file.ifc", workspace)
    assert str(result).startswith(str(workspace.resolve()))


def test_validate_path_symlink_escapes_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace / "evil_link"
    link.symlink_to(outside)
    with pytest.raises(PathNotAllowedError, match="outside"):
        validate_path(link / "file.ifc", workspace)


def test_validate_path_symlink_to_etc(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    link = workspace / "evil"
    link.symlink_to(Path("/etc"))
    with pytest.raises(PathNotAllowedError, match="outside"):
        validate_path(link / "passwd", workspace)


# ---------------------------------------------------------------------------
# validate_path — UNC paths
# ---------------------------------------------------------------------------


def test_validate_path_rejects_unc_backslash(tmp_path: Path) -> None:
    with pytest.raises(PathNotAllowedError, match="UNC"):
        validate_path(Path("\\\\server\\share\\file.ifc"), tmp_path)


def test_validate_path_rejects_unc_forward_slash(tmp_path: Path) -> None:
    with pytest.raises(PathNotAllowedError, match="UNC"):
        validate_path(Path("//server/share/file.ifc"), tmp_path)


# ---------------------------------------------------------------------------
# validate_arg_size
# ---------------------------------------------------------------------------


def test_validate_arg_size_within_limit() -> None:
    args = {"key": "value"}
    validate_arg_size(args, max_bytes=1024)  # should not raise


def test_validate_arg_size_exact_limit() -> None:
    # Build payload that is exactly max_bytes
    payload = json.dumps({"k": "v"}, separators=(",", ":")).encode()
    validate_arg_size({"k": "v"}, max_bytes=len(payload))  # should not raise


def test_validate_arg_size_over_limit() -> None:
    large = {"data": "x" * 2000}
    with pytest.raises(ArgSizeTooLargeError, match="exceeds cap"):
        validate_arg_size(large, max_bytes=100)


def test_validate_arg_size_deeply_nested() -> None:
    # Deeply nested dict — should be caught by size cap even if small per level
    def _nest(depth: int) -> dict[str, Any]:
        if depth == 0:
            return {"v": "leaf"}
        return {"n": _nest(depth - 1)}

    deep = _nest(500)
    encoded_len = len(json.dumps(deep, separators=(",", ":")).encode())
    # Under the default 1 MiB cap but test the function works correctly
    validate_arg_size(deep, max_bytes=encoded_len + 1)
    with pytest.raises(ArgSizeTooLargeError):
        validate_arg_size(deep, max_bytes=encoded_len - 1)


def test_validate_arg_size_huge_string() -> None:
    huge = {"data": "A" * (2 * 1024 * 1024)}  # 2 MiB string
    with pytest.raises(ArgSizeTooLargeError):
        validate_arg_size(huge, max_bytes=1024 * 1024)


# ---------------------------------------------------------------------------
# check_ifc_export_size
# ---------------------------------------------------------------------------


def test_ifc_export_size_file_not_exist(tmp_path: Path) -> None:
    nonexistent = tmp_path / "missing.ifc"
    result = check_ifc_export_size(nonexistent, warn_bytes=100, max_bytes=1000)
    assert result is False


def test_ifc_export_size_small_file(tmp_path: Path) -> None:
    f = tmp_path / "small.ifc"
    f.write_bytes(b"x" * 50)
    result = check_ifc_export_size(f, warn_bytes=100, max_bytes=1000)
    assert result is False


def test_ifc_export_size_warn_threshold(tmp_path: Path) -> None:
    f = tmp_path / "large.ifc"
    f.write_bytes(b"x" * 200)
    result = check_ifc_export_size(f, warn_bytes=100, max_bytes=1000)
    assert result is True


def test_ifc_export_size_hard_limit(tmp_path: Path) -> None:
    f = tmp_path / "huge.ifc"
    f.write_bytes(b"x" * 2000)
    with pytest.raises(ValueError, match="exceeds hard limit"):
        check_ifc_export_size(f, warn_bytes=100, max_bytes=1000)


# ---------------------------------------------------------------------------
# TCP token auth — wrong token rejected via hmac.compare_digest
# ---------------------------------------------------------------------------


def _run_fake_tcp_server_test(
    server_token: str,
    client_token: str,
) -> bool:
    """Helper: run a fake TCP server, return True if client connected successfully."""
    import anyio
    import anyio.abc

    from allplan_mcp_server.ipc.framing import encode
    from allplan_mcp_server.ipc.tcp import TcpTransport
    from allplan_mcp_server.ipc.transport import AuthError

    connected = False

    async def _handle_client(conn: anyio.abc.ByteStream) -> None:
        import contextlib
        async with conn:
            await conn.send(encode({"hello": server_token}))
            with contextlib.suppress(Exception):
                await conn.receive(1024)

    async def _run() -> None:
        nonlocal connected
        listener = await anyio.create_tcp_listener(local_host="127.0.0.1", local_port=0)
        # Retrieve the assigned port from the first listener socket
        raw_sock = listener.listeners[0].extra(anyio.abc.SocketAttribute.raw_socket)
        port = raw_sock.getsockname()[1]

        async with anyio.create_task_group() as tg:
            tg.start_soon(listener.serve, _handle_client)
            transport = TcpTransport(host="127.0.0.1", port=port, token=client_token)
            try:
                await transport.connect()
                connected = True
                await transport.close()
            except AuthError:
                connected = False
            tg.cancel_scope.cancel()

    anyio.run(_run)
    return connected


def test_tcp_wrong_token_rejected() -> None:
    """TcpTransport.connect rejects a mismatched hello token."""
    assert _run_fake_tcp_server_test("wrong_token", "correct_token") is False


def test_tcp_correct_token_accepted() -> None:
    """TcpTransport.connect accepts a matching hello token."""
    assert _run_fake_tcp_server_test("s3cr3t_token", "s3cr3t_token") is True


def test_tcp_empty_token_rejected() -> None:
    """Empty client token must not match a non-empty server token."""
    assert _run_fake_tcp_server_test("real_token", "") is False


# ---------------------------------------------------------------------------
# Oversized frame — rejected without parsing
# ---------------------------------------------------------------------------


def test_oversized_frame_rejected_without_parsing() -> None:
    """Frames exceeding the cap yield an error sentinel; no JSON parsing attempted."""
    import anyio

    from allplan_mcp_server.ipc.framing import decode_stream

    async def _run() -> None:
        # Build a frame header claiming 32 MiB payload — way over the 16 MiB cap.
        CLAIMED_SIZE = 32 * 1024 * 1024
        header = struct.pack(">I", CLAIMED_SIZE)
        # Provide only the 4-byte header — stream closes before payload.
        # We need a stream object; use a simple fake.

        class _FakeReader:
            def __init__(self, data: bytes) -> None:
                self._data = data
                self._pos = 0

            async def receive_exactly(self, n: int) -> bytes:
                chunk = self._data[self._pos : self._pos + n]
                self._pos += n
                if not chunk:
                    raise EOFError("end of fake stream")
                return chunk

        reader = _FakeReader(header)
        results = []
        async for msg in decode_stream(reader, max_frame_bytes=16 * 1024 * 1024):
            results.append(msg)

        assert len(results) == 1
        assert results[0]["error"]["code"] == "FrameTooLarge"

    anyio.run(_run)


def test_oversized_frame_agent_survives() -> None:
    """After rejecting an oversized frame, the sentinel error is well-formed."""
    import anyio

    from allplan_mcp_server.ipc.framing import decode_stream

    async def _run() -> None:
        class _FakeReader:
            def __init__(self, data: bytes) -> None:
                self._chunks = [data]
                self._idx = 0

            async def receive_exactly(self, n: int) -> bytes:
                if self._idx >= len(self._chunks):
                    raise EOFError
                chunk = self._chunks[self._idx][:n]
                self._chunks[self._idx] = self._chunks[self._idx][n:]
                if not self._chunks[self._idx]:
                    self._idx += 1
                return chunk

        big_header = struct.pack(">I", 20 * 1024 * 1024)
        reader = _FakeReader(big_header)
        msgs = [m async for m in decode_stream(reader)]
        assert msgs[0]["ok"] is False
        assert msgs[0]["error"]["code"] == "FrameTooLarge"

    anyio.run(_run)


# ---------------------------------------------------------------------------
# Pathological JSON inputs — rejected at framing layer
# ---------------------------------------------------------------------------


def test_invalid_utf8_payload_rejected() -> None:
    """Non-UTF-8 bytes in the payload yield an Internal error sentinel."""
    import anyio

    from allplan_mcp_server.ipc.framing import decode_stream

    async def _run() -> None:
        bad_payload = b"\xff\xfe\xfd"  # invalid UTF-8
        header = struct.pack(">I", len(bad_payload))

        class _FakeReader:
            def __init__(self) -> None:
                self._data = header + bad_payload
                self._pos = 0

            async def receive_exactly(self, n: int) -> bytes:
                chunk = self._data[self._pos : self._pos + n]
                self._pos += n
                if not chunk:
                    raise EOFError
                return chunk

        msgs = [m async for m in decode_stream(_FakeReader())]
        assert msgs[0]["ok"] is False
        assert msgs[0]["error"]["code"] == "Internal"

    anyio.run(_run)


def test_truncated_frame_rejected() -> None:
    """Stream closing mid-payload yields AgentDisconnected sentinel."""
    import anyio

    from allplan_mcp_server.ipc.framing import decode_stream

    async def _run() -> None:
        # Header says 100 bytes but only 10 provided.
        header = struct.pack(">I", 100)
        short_payload = b"x" * 10

        class _FakeReader:
            def __init__(self) -> None:
                self._data = header + short_payload
                self._pos = 0

            async def receive_exactly(self, n: int) -> bytes:
                chunk = self._data[self._pos : self._pos + n]
                self._pos += n
                if len(chunk) < n:
                    raise EOFError("truncated")
                return chunk

        msgs = [m async for m in decode_stream(_FakeReader())]
        assert msgs[0]["ok"] is False
        assert msgs[0]["error"]["code"] == "AgentDisconnected"

    anyio.run(_run)


# ---------------------------------------------------------------------------
# IpcClient arg size enforcement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ipc_client_rejects_oversized_args() -> None:
    """IpcClient.call raises IpcError(InvalidArgs) for oversized args."""
    from unittest.mock import MagicMock

    from allplan_mcp_server.ipc.client import IpcClient, IpcError
    from allplan_mcp_server.ipc.transport import Transport

    mock_transport = MagicMock(spec=Transport)
    mock_transport.is_connected = True
    client = IpcClient(lambda: mock_transport, max_arg_bytes=100)
    client._transport = mock_transport

    huge_args = {"data": "x" * 200}
    with pytest.raises(IpcError) as exc_info:
        await client.call("create_wall", huge_args, timeout=5.0)
    assert exc_info.value.code == "InvalidArgs"


@pytest.mark.asyncio
async def test_ipc_client_accepts_normal_args() -> None:
    """IpcClient.call proceeds past size check for small args (send may fail; that's OK)."""
    from unittest.mock import AsyncMock, MagicMock

    from allplan_mcp_server.ipc.client import IpcClient, IpcError
    from allplan_mcp_server.ipc.transport import Transport

    mock_transport = MagicMock(spec=Transport)
    mock_transport.is_connected = True
    mock_transport.send = AsyncMock(side_effect=Exception("send failed"))
    client = IpcClient(lambda: mock_transport, max_arg_bytes=1024 * 1024)
    client._transport = mock_transport

    small_args = {"key": "value"}
    with pytest.raises(IpcError) as exc_info:
        await client.call("create_wall", small_args, timeout=5.0)
    # Send failed (not InvalidArgs), so the size check passed
    assert exc_info.value.code == "AgentDisconnected"


# ---------------------------------------------------------------------------
# TcpTransport rejects non-loopback host
# ---------------------------------------------------------------------------


def test_tcp_transport_allows_non_loopback() -> None:
    # WSL2 ↔ Windows requires cross-network TCP (e.g. 10.255.255.254).
    # TcpTransport no longer restricts to loopback; token auth is the security layer.
    from allplan_mcp_server.ipc.tcp import TcpTransport

    t = TcpTransport(host="10.255.255.254", port=9999, token="tok")
    assert t._host == "10.255.255.254"


def test_tcp_transport_allows_loopback() -> None:
    from allplan_mcp_server.ipc.tcp import TcpTransport

    t = TcpTransport(host="127.0.0.1", port=9999, token="tok")
    assert t._host == "127.0.0.1"


# ---------------------------------------------------------------------------
# IpcError correlation_id
# ---------------------------------------------------------------------------


def test_ipc_error_has_correlation_id() -> None:
    from allplan_mcp_server.ipc.client import IpcError

    err = IpcError("Internal", "boom")
    assert err.correlation_id
    # UUID4 format: 8-4-4-4-12 hex chars
    parts = err.correlation_id.split("-")
    assert len(parts) == 5


def test_ipc_error_str_includes_correlation_id() -> None:
    from allplan_mcp_server.ipc.client import IpcError

    err = IpcError("AllplanApiError", "wall failed", correlation_id="test-cid-123")
    s = str(err)
    assert "AllplanApiError" in s
    assert "wall failed" in s
    assert "test-cid-123" in s


def test_ipc_error_custom_correlation_id() -> None:
    from allplan_mcp_server.ipc.client import IpcError

    err = IpcError("Timeout", "no reply", correlation_id="my-cid")
    assert err.correlation_id == "my-cid"
