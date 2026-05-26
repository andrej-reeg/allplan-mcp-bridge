"""Tests for ipc/framing.py."""

import struct
from typing import Any

import anyio
import pytest

from allplan_mcp_server.ipc.framing import DEFAULT_MAX_FRAME_BYTES, decode_stream, encode

# --- helpers ---


class _BytesReader:
    """Minimal anyio-compatible reader backed by a bytes buffer."""

    def __init__(self, data: bytes) -> None:
        self._buf = bytearray(data)
        self._pos = 0

    async def receive_exactly(self, n: int) -> bytes:
        chunk = self._buf[self._pos : self._pos + n]
        if len(chunk) < n:
            raise anyio.EndOfStream
        self._pos += n
        return bytes(chunk)


def _frames(*objs: dict[str, Any]) -> bytes:
    return b"".join(encode(o) for o in objs)


# --- encode / decode round-trips ---


def test_encode_produces_length_prefix() -> None:
    frame = encode({"ok": True})
    (length,) = struct.unpack(">I", frame[:4])
    assert length == len(frame) - 4


@pytest.mark.anyio
async def test_roundtrip_single_message() -> None:
    obj = {"id": "abc", "cmd": "ping", "args": {}}
    reader = _BytesReader(encode(obj))
    results = [msg async for msg in decode_stream(reader)]
    assert results == [obj]


@pytest.mark.anyio
async def test_roundtrip_multiple_messages() -> None:
    msgs = [{"id": str(i), "v": i} for i in range(5)]
    reader = _BytesReader(_frames(*msgs))
    results = [msg async for msg in decode_stream(reader)]
    assert results == msgs


@pytest.mark.anyio
async def test_empty_stream_yields_nothing() -> None:
    reader = _BytesReader(b"")
    results = [msg async for msg in decode_stream(reader)]
    assert results == []


# --- error cases ---


@pytest.mark.anyio
async def test_truncated_header_yields_nothing() -> None:
    reader = _BytesReader(b"\x00\x00")  # only 2 bytes, need 4
    results = [msg async for msg in decode_stream(reader)]
    # EOF before full header — clean stop, no sentinel
    assert results == []


@pytest.mark.anyio
async def test_truncated_payload_yields_sentinel() -> None:
    payload = b'{"ok":true}'
    header = struct.pack(">I", len(payload) + 10)  # claims more bytes than available
    reader = _BytesReader(header + payload)
    results = [msg async for msg in decode_stream(reader)]
    assert len(results) == 1
    assert results[0]["error"]["code"] == "AgentDisconnected"


@pytest.mark.anyio
async def test_oversized_frame_yields_sentinel_before_parse() -> None:
    big = DEFAULT_MAX_FRAME_BYTES + 1
    header = struct.pack(">I", big)
    reader = _BytesReader(header)  # payload never sent — should be rejected at header
    results = [msg async for msg in decode_stream(reader)]
    assert len(results) == 1
    assert results[0]["error"]["code"] == "FrameTooLarge"


@pytest.mark.anyio
async def test_invalid_json_yields_sentinel() -> None:
    payload = b"not json at all!!!"
    frame = struct.pack(">I", len(payload)) + payload
    reader = _BytesReader(frame)
    results = [msg async for msg in decode_stream(reader)]
    assert len(results) == 1
    assert results[0]["error"]["code"] == "Internal"


@pytest.mark.anyio
async def test_custom_max_frame_size() -> None:
    payload = b'{"x":1}'
    header = struct.pack(">I", len(payload))
    reader = _BytesReader(header + payload)
    results = [msg async for msg in decode_stream(reader, max_frame_bytes=3)]
    assert results[0]["error"]["code"] == "FrameTooLarge"


@pytest.mark.anyio
async def test_stream_stops_after_error() -> None:
    """After a sentinel, no further messages are yielded."""
    bad_payload = b"not json"
    bad_frame = struct.pack(">I", len(bad_payload)) + bad_payload
    good_frame = encode({"ok": True})
    reader = _BytesReader(bad_frame + good_frame)
    results = [msg async for msg in decode_stream(reader)]
    assert len(results) == 1  # only the sentinel, not the good frame after it
    assert results[0]["error"]["code"] == "Internal"
