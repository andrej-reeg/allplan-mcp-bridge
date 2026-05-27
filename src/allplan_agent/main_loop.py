"""Main-thread drain loop for the Allplan agent.

pump_once() MUST be called exclusively from Allplan's main thread.
It is not async — Allplan's embedded Python does not use asyncio.
"""

import logging
import time
from typing import Any

from . import handlers as _handlers  # noqa: F401 — registers all @command decorators
from .command_queue import Command, CommandQueue
from .dispatcher import dispatch
from .safety import undo_bracket

_log = logging.getLogger(__name__)


def _resolve_command(cmd: Command) -> dict[str, Any]:
    """Run a single command inside an undo bracket. Returns a result dict."""
    with undo_bracket(cmd.cmd_name):
        return dispatch(cmd.cmd_name, cmd.args)


def pump_once(q: CommandQueue, max_items: int = 8) -> int:
    """Drain up to max_items commands from the queue and execute them.

    Returns the number of commands processed.
    Exceptions from individual commands never propagate — they are captured
    into the command's Future so the caller gets a proper error response.

    Invariants:
    - Called on the main thread only.
    - Handler functions run synchronously on this call stack.
    - No asyncio, no threads spawned here.
    """
    commands = q.drain(max_items)
    if commands:
        _log.debug("pump_once.drain count=%d", len(commands))
    now = time.monotonic()

    for cmd in commands:
        if now > cmd.deadline_at:
            _log.warning("pump_once.deadline_exceeded cmd_id=%s cmd=%s", cmd.id, cmd.cmd_name)
            if not cmd.future.done():
                cmd.future.set_exception(
                    TimeoutError(f"Deadline exceeded for {cmd.cmd_name!r}")
                )
            continue

        t0 = time.monotonic()
        try:
            result = _resolve_command(cmd)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            _log.info(
                "pump_once.ok cmd_id=%s cmd=%s elapsed_ms=%d", cmd.id, cmd.cmd_name, elapsed_ms
            )
            if not cmd.future.done():
                cmd.future.set_result(result)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            _log.error(
                "pump_once.error cmd_id=%s cmd=%s error=%s elapsed_ms=%d",
                cmd.id, cmd.cmd_name, exc, elapsed_ms,
            )
            if not cmd.future.done():
                cmd.future.set_exception(exc)

    return len(commands)
