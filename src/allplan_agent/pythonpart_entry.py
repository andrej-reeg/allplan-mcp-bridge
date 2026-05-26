"""Allplan PythonPart entry hooks for the MCP bridge.

This file is loaded by Allplan when the user activates the "Allplan MCP Bridge"
PythonPart from the toolbox. It starts the IPC listener thread and registers a
Qt timer that calls pump_once() on the Allplan main thread at a fixed interval.

Threading law: this module only calls pump_once() from the main thread (via Qt
timer callback). It never calls NemAll_Python_* directly.

ALLPLAN 2026 NOTES:
  - CreateElement is called on the main thread when the user places/activates
    the PythonPart. It returns empty geometry (this PythonPart creates nothing).
  - Allplan ships PySide2 (older builds) or PySide6 (2026+). We try both.
  - The .pyp companion file (AllplanMcpBridge.pyp) defines the UI palette.
  - VERIFY: function names and return signatures against the installed Allplan
    2026 SDK before deploying. Allplan API details are not guessable safely.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import threading

from .command_queue import CommandQueue
from .main_loop import pump_once

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bridge state — written on the main thread at activation time, read-only
# after that. No locks needed as long as CreateElement is single-threaded.
# ---------------------------------------------------------------------------

_state: dict[str, Any] = {
    "started": False,
    "listener": None,
    "queue": None,
    "timer": None,
    "transport_addr": None,
}

_DRAIN_INTERVAL_MS = 100  # pump_once() frequency (milliseconds)
_QUEUE_MAXSIZE = 256
_CONFIG_FILENAME = "bridge_config.json"


# ---------------------------------------------------------------------------
# Qt timer helper
# ---------------------------------------------------------------------------


def _get_timer_class() -> type | None:
    """Try to import QTimer from PySide2 or PySide6 (both ship with Allplan)."""
    for module_name in ("PySide6.QtCore", "PySide2.QtCore"):
        try:
            import importlib

            m = importlib.import_module(module_name)
            return m.QTimer  # type: ignore[no-any-return]
        except (ImportError, AttributeError):
            continue
    return None


# ---------------------------------------------------------------------------
# Bridge start / stop
# ---------------------------------------------------------------------------


def _load_config() -> dict[str, Any]:
    """Load bridge_config.json from the same directory as this file."""
    config_path = Path(__file__).parent / _CONFIG_FILENAME
    if not config_path.exists():
        _log.warning("bridge.config_missing path=%s using_defaults=True", config_path.name)
        return {}
    try:
        return dict(json.loads(config_path.read_text(encoding="utf-8")))
    except Exception as exc:
        _log.error("bridge.config_load_failed error=%s", exc)
        return {}


def start_bridge() -> None:
    """Start the IPC listener and drain timer. Safe to call multiple times (idempotent)."""
    if _state["started"]:
        _log.info("bridge.already_started")
        return

    config = _load_config()
    queue: CommandQueue = CommandQueue(maxsize=_QUEUE_MAXSIZE)

    # Prefer named pipe on Windows; fall back to TCP elsewhere (tests / CI).
    listener: threading.Thread
    if sys.platform == "win32":
        from .listener import NamedPipeListenerThread

        pipe_name = config.get("pipe_name", r"\\.\pipe\allplan-mcp-bridge")
        listener = NamedPipeListenerThread(
            q=queue,
            pipe_name=str(pipe_name),
            request_timeout=float(config.get("request_timeout", 10.0)),
        )
        _state["transport_addr"] = pipe_name
    else:
        from .listener import TcpListenerThread

        host = str(config.get("tcp_host", "127.0.0.1"))
        port = int(config.get("tcp_port", 49152))
        listener = TcpListenerThread(
            q=queue,
            host=host,
            port=port,
            request_timeout=float(config.get("request_timeout", 10.0)),
        )
        _state["transport_addr"] = f"{host}:{port}"

    listener.start()
    _state.update({"started": True, "listener": listener, "queue": queue})

    # Register a recurring Qt timer to drain the command queue on the main thread.
    QTimer = _get_timer_class()
    if QTimer is not None:
        timer = QTimer()
        timer.timeout.connect(lambda: pump_once(queue))
        timer.start(_DRAIN_INTERVAL_MS)
        _state["timer"] = timer
        _log.info(
            "bridge.timer_registered interval_ms=%d transport=%s",
            _DRAIN_INTERVAL_MS,
            _state["transport_addr"],
        )
    else:
        # No Qt available — manual pump_once() calls required (e.g. from tests).
        _log.warning(
            "bridge.no_qt Qt not importable; pump_once() will not run automatically. "
            "Allplan API calls will not execute until a timer is wired up externally."
        )

    _log.info("bridge.started transport=%s", _state["transport_addr"])


def stop_bridge() -> None:
    """Stop the listener thread and Qt timer. Safe to call multiple times."""
    if not _state["started"]:
        return

    if _state["timer"] is not None:
        with contextlib.suppress(Exception):
            _state["timer"].stop()
        _state["timer"] = None

    if _state["listener"] is not None:
        with contextlib.suppress(Exception):
            _state["listener"].stop()
        _state["listener"] = None

    _state.update({"started": False, "queue": None, "transport_addr": None})
    _log.info("bridge.stopped")


def get_status() -> dict[str, Any]:
    """Return bridge status for palette display or health checks."""
    return {
        "running": bool(_state["started"]),
        "transport": str(_state["transport_addr"] or "—"),
        "queue_depth": _state["queue"].size if _state["queue"] is not None else 0,
    }


# ---------------------------------------------------------------------------
# Allplan PythonPart entry hooks
#
# ALLPLAN 2026 VERIFY: confirm exact function names, parameter types, and
# return conventions against the installed Allplan 2026 Python SDK before
# deploying.  Allplan has changed these signatures between major versions.
# ---------------------------------------------------------------------------


def CreateElement(  # noqa: N802  (Allplan mandates PascalCase)
    build_ele: Any,
    doc: Any,
) -> tuple[list[Any], list[Any], Any]:
    """Allplan entry point — called on the main thread when PythonPart activates.

    Starts the IPC bridge (idempotent). Returns empty element/attribute lists
    because this PythonPart creates no visual geometry.

    ALLPLAN 2026 VERIFY:
    - Exact return type (some versions expect a 2-tuple, others 3-tuple).
    - Whether `build_ele.pyp_params` exists and is the correct third element.
    """
    start_bridge()
    pyp_params = getattr(build_ele, "pyp_params", None)
    return [], [], pyp_params


def on_cancel_function(  # noqa: N802
    build_ele: Any,
    doc: Any,
) -> tuple[bool, list[Any], list[Any], Any]:
    """Called when the user cancels or replaces the PythonPart.

    ALLPLAN 2026 VERIFY: function name may differ (e.g. OnCancelFunction).
    """
    stop_bridge()
    return True, [], [], None
