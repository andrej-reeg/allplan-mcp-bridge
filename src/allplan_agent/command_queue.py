"""Thread-safe command queue for the main-thread drain loop."""

import queue
import time
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any


class QueueFullError(Exception):
    """Raised when the command queue is at capacity."""


@dataclass
class Command:
    id: str
    cmd_name: str
    args: dict[str, Any]
    future: "Future[dict[str, Any]]"
    deadline_at: float  # monotonic seconds


class CommandQueue:
    """Bounded, thread-safe queue of Commands.

    Enqueue from the listener thread; drain from the main (Allplan) thread.
    The queue is the ONLY shared mutable state between those two threads.
    """

    def __init__(self, maxsize: int = 256) -> None:
        self._q: queue.Queue[Command] = queue.Queue(maxsize=maxsize)

    def enqueue(self, cmd: Command) -> None:
        """Add a command. Raises QueueFullError if at capacity."""
        try:
            self._q.put_nowait(cmd)
        except queue.Full as exc:
            raise QueueFullError(
                f"Command queue full (maxsize={self._q.maxsize})"
            ) from exc

    def drain(self, max_items: int = 8) -> list[Command]:
        """Remove up to max_items commands without blocking. Called from main thread."""
        items: list[Command] = []
        for _ in range(max_items):
            try:
                items.append(self._q.get_nowait())
            except queue.Empty:
                break
        return items

    @property
    def size(self) -> int:
        return self._q.qsize()

    def make_command(
        self,
        cmd_id: str,
        cmd_name: str,
        args: dict[str, Any],
        timeout_seconds: float,
    ) -> tuple["Command", "Future[dict[str, Any]]"]:
        """Convenience factory: create a Command + its Future together."""
        fut: Future[dict[str, Any]] = Future()
        cmd = Command(
            id=cmd_id,
            cmd_name=cmd_name,
            args=args,
            future=fut,
            deadline_at=time.monotonic() + timeout_seconds,
        )
        return cmd, fut
