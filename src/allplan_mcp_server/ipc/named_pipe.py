"""Windows named pipe transport.

On non-Windows platforms this module raises ``NotImplementedError`` at connect
time, allowing imports to succeed on Linux CI while keeping the Windows-only
implementation path clear.
"""

import sys

import anyio

from .transport import TransportClosedError, TransportError, _receive_exactly


class NamedPipeTransport:
    """Client-side Windows named pipe transport.

    The pipe name must include a per-session suffix (e.g. Allplan PID) so
    multiple Allplan instances do not share the same pipe.

    ACL enforcement is on the server (agent) side: the pipe is created with an
    ACL restricting connections to the current user's SID. This client does not
    need to enforce it — OS-level ACL rejects unauthorized callers before
    ``connect()`` returns.
    """

    def __init__(self, pipe_name: str) -> None:
        self._pipe_name = pipe_name
        self._stream: anyio.abc.ByteStream | None = None

    @property
    def is_connected(self) -> bool:
        return self._stream is not None

    async def connect(self) -> None:
        if sys.platform != "win32":
            raise NotImplementedError(
                "NamedPipeTransport is only supported on Windows. "
                "Use TcpTransport on this platform."
            )
        try:
            # anyio exposes named-pipe support on Windows via the trio/asyncio backend.
            # The pipe name must be in UNC form: \\.\pipe\<name>
            self._stream = await anyio.connect_unix(self._pipe_name)
        except Exception as exc:
            raise TransportError(
                f"Could not connect to named pipe {self._pipe_name!r}: {exc}"
            ) from exc

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
