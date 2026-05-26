"""Length-prefixed JSON codec: 4-byte big-endian uint32 + UTF-8 JSON payload."""

import json
import struct
from collections.abc import AsyncIterator
from typing import Any

DEFAULT_MAX_FRAME_BYTES = 16 * 1024 * 1024  # 16 MiB

_HEADER = struct.Struct(">I")  # big-endian uint32

_ERROR_TRUNCATED: dict[str, Any] = {
    "ok": False,
    "error": {"code": "AgentDisconnected", "message": "Connection closed mid-frame"},
}
_ERROR_OVERSIZED: dict[str, Any] = {
    "ok": False,
    "error": {"code": "FrameTooLarge", "message": "Incoming frame exceeds size cap"},
}
_ERROR_INVALID_JSON: dict[str, Any] = {
    "ok": False,
    "error": {"code": "Internal", "message": "Frame payload is not valid JSON"},
}


def encode(obj: dict[str, Any]) -> bytes:
    """Encode a dict as a length-prefixed UTF-8 JSON frame."""
    payload = json.dumps(obj, separators=(",", ":")).encode()
    return _HEADER.pack(len(payload)) + payload


async def decode_stream(
    reader: Any,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
) -> AsyncIterator[dict[str, Any]]:
    """Yield dicts from an anyio ByteStream.

    Never raises. On read error or malformed input, yields a sentinel error
    dict and stops iteration.

    reader must support ``read_exactly(n: int) -> bytes`` (anyio ByteStream).
    """
    while True:
        try:
            header = await reader.receive_exactly(_HEADER.size)
        except Exception:
            # EOF or connection closed — normal exit, no sentinel
            return

        (length,) = _HEADER.unpack(header)

        if length > max_frame_bytes:
            yield _ERROR_OVERSIZED
            return

        try:
            payload = await reader.receive_exactly(length)
        except Exception:
            yield _ERROR_TRUNCATED
            return

        try:
            yield json.loads(payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            yield _ERROR_INVALID_JSON
            return
