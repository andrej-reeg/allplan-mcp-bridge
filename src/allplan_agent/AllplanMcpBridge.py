"""Allplan 2026 PythonPart entry point for the MCP Bridge.

Loaded by Allplan from:  <PythonPartsScripts>/allplan_agent/AllplanMcpBridge.py
PYP <Name> field:        allplan_agent\\AllplanMcpBridge.py

Threading law: pump_once() is called exclusively from the main thread via a
QTimer (PySide6/PySide2, both ship with Allplan). The listener thread NEVER
calls Allplan APIs directly.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# sys.path setup.
# __file__ == <PythonPartsScripts>/allplan_agent/AllplanMcpBridge.py
#
# _scripts_root  (<PythonPartsScripts>/) — makes `allplan_agent` importable
#                as a package.
# _agent_root    (<PythonPartsScripts>/allplan_agent/) — makes the vendored
#                `allplan_mcp_server` shim importable as `allplan_mcp_server`
#                (handlers use `from allplan_mcp_server.models import ...`).
# ---------------------------------------------------------------------------
_scripts_root = str(Path(__file__).resolve().parent.parent)
_agent_root = str(Path(__file__).resolve().parent)
if _scripts_root not in sys.path:
    sys.path.insert(0, _scripts_root)
if _agent_root not in sys.path:
    sys.path.insert(0, _agent_root)

from allplan_agent.command_queue import CommandQueue  # noqa: E402
from allplan_agent.main_loop import pump_once  # noqa: E402

_log = logging.getLogger(__name__)

def _dlog(msg: str) -> None:
    """Direct-to-file debug log bypassing the Python logging framework."""
    import datetime
    import os
    try:
        log_dir = os.path.join(os.path.expanduser("~"), ".allplan-mcp")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "debug.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().isoformat()} {msg}\n")
    except Exception:
        pass

# File logger — writes to ~/.allplan-mcp/bridge.log so we can diagnose issues
# even when Allplan's embedded Python captures stdout/stderr.
def _setup_file_logging() -> None:
    import os
    log_dir = Path(os.path.expanduser("~")) / ".allplan-mcp"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "bridge.log"
    handler = logging.FileHandler(str(log_file), encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    already = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(log_file)
        for h in root.handlers
    )
    if not already:
        root.addHandler(handler)
    root.setLevel(logging.DEBUG)

with contextlib.suppress(Exception):
    _setup_file_logging()
_dlog("AllplanMcpBridge module loaded")

_DRAIN_INTERVAL_MS = 100
_QUEUE_MAXSIZE = 256
_CONFIG_FILENAME = "bridge_config.json"

# Module-level state — written once on the main thread during init, then read-only.
_queue: CommandQueue | None = None
_listener: Any = None
_timer: Any = None
_transport_addr: str | None = None
_started: bool = False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _load_config() -> dict[str, Any]:
    config_path = Path(__file__).parent / _CONFIG_FILENAME
    if not config_path.exists():
        _log.warning("bridge.config_missing using_defaults=True")
        return {}
    try:
        return dict(json.loads(config_path.read_text(encoding="utf-8")))
    except Exception as exc:
        _log.error("bridge.config_load_failed error=%s", exc)
        return {}


# ---------------------------------------------------------------------------
# Timer — QTimer only (ships with Allplan via PySide6/PySide2)
# ---------------------------------------------------------------------------


def _start_timer(queue: CommandQueue) -> Any:
    """Start a QTimer to drain the command queue on the Allplan main thread.

    PySide6 ships with Allplan 2026; PySide2 with older builds. Either works.
    Falls back gracefully to None — commands drain via notify_fn + mouse events.
    """
    for qt_mod in ("PySide6.QtCore", "PySide2.QtCore"):
        try:
            import importlib
            m = importlib.import_module(qt_mod)
            t = m.QTimer()
            t.timeout.connect(lambda: pump_once(queue))
            t.start(_DRAIN_INTERVAL_MS)
            _log.info(
                "bridge.timer type=QTimer module=%s interval_ms=%d",
                qt_mod,
                _DRAIN_INTERVAL_MS,
            )
            _dlog(f"bridge.timer started module={qt_mod} interval_ms={_DRAIN_INTERVAL_MS}")
            return t
        except Exception as exc:
            _dlog(f"bridge.timer failed module={qt_mod} error={exc}")

    _log.warning(
        "bridge.no_timer QTimer unavailable. "
        "Commands drain via notify_fn + on_preview_draw/process_mouse_msg."
    )
    _dlog("bridge.no_timer QTimer unavailable")
    return None


def _resolve_qt_module() -> Any:
    """Return the first importable Qt core module, or None."""
    import importlib
    for qt_mod in ("PySide6.QtCore", "PySide2.QtCore"):
        try:
            return importlib.import_module(qt_mod)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Bridge lifecycle
# ---------------------------------------------------------------------------


def _write_token(token: str, token_file_path: str) -> None:
    """Write TCP auth token to the user's home directory."""
    import stat as _stat

    p = Path(token_file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token, encoding="utf-8")
    with contextlib.suppress(Exception):
        p.chmod(_stat.S_IRUSR | _stat.S_IWUSR)  # 0600 — best-effort on Windows


def start_bridge() -> None:
    global _queue, _listener, _timer, _transport_addr, _started, pump_once
    if _started:
        return

    # Purge stale allplan_agent submodule cache so @command decorators
    # re-execute on every bridge restart (cancel + reactivate).
    _this_module = __name__
    for _k in list(sys.modules):
        if _k.startswith("allplan_agent.") and _k != _this_module:
            del sys.modules[_k]

    # Re-import after purge so we reference freshly-loaded modules.
    from allplan_agent.main_loop import pump_once as _pump_once  # noqa: PLC0415
    pump_once = _pump_once

    import os as _os
    import secrets

    config = _load_config()
    _queue = CommandQueue(maxsize=_QUEUE_MAXSIZE)

    force_tcp: bool = bool(config.get("force_tcp", False))
    timeout = float(config.get("request_timeout", 10.0))

    _pywin32_ok = False
    try:
        import win32pipe  # type: ignore[import-untyped]  # noqa: F401
        _pywin32_ok = True
    except ImportError:
        pass

    if sys.platform == "win32" and not force_tcp and _pywin32_ok:
        from allplan_agent.listener import NamedPipeListenerThread

        pipe_name = config.get("pipe_name", r"\\.\pipe\allplan-mcp-bridge")
        _listener = NamedPipeListenerThread(
            q=_queue,
            pipe_name=str(pipe_name),
            request_timeout=timeout,
        )
        _transport_addr = str(pipe_name)
    else:
        if sys.platform == "win32" and not force_tcp and not _pywin32_ok:
            _log.info("bridge.pywin32_unavailable falling_back_to=tcp")
        from allplan_agent.listener import TcpListenerThread

        host = str(config.get("tcp_host", "127.0.0.1"))
        port = int(config.get("tcp_port", 49152))
        token = secrets.token_hex(32)
        _default_token_file = _os.path.join(_os.path.expanduser("~"), ".allplan-mcp", "token")
        token_file = str(config.get("tcp_token_file", _default_token_file))
        _write_token(token, token_file)

        _listener = TcpListenerThread(
            q=_queue,
            host=host,
            port=port,
            request_timeout=timeout,
            token=token,
        )
        _transport_addr = f"{host}:{port}"

    _listener.start()
    _timer = _start_timer(_queue)

    # Wire QTimer.singleShot wakeup: listener thread posts pump_once to main
    # thread event loop on every enqueue — works even without the repeating timer.
    _qt = _resolve_qt_module()
    if _qt is not None and _queue is not None:
        _q_ref = _queue
        _p_ref = pump_once
        _qt_ref = _qt
        def _qt_notify() -> None:
            _qt_ref.QTimer.singleShot(0, lambda: _p_ref(_q_ref))
        _queue.notify_fn = _qt_notify
        _dlog("bridge.notify_fn set via QTimer.singleShot")
    else:
        qt_state = "None" if _qt is None else "ok"
        q_state = "None" if _queue is None else "ok"
        _dlog(f"bridge.notify_fn NOT set (Qt={qt_state} queue={q_state})")

    _started = True
    _log.info("bridge.started transport=%s", _transport_addr)
    _notify_set = _queue.notify_fn is not None if _queue else False
    _dlog(
        f"bridge.started transport={_transport_addr}"
        f" timer={_timer is not None} notify_fn={_notify_set}"
    )

    # Background polling thread: calls pump_once every 200 ms on a daemon thread.
    # Guarantees commands are processed even when QTimer and mouse events are absent.
    # Commands that call Allplan APIs unsafely will return an error, not a timeout.
    import threading as _threading
    import time as _time

    _q_bg = _queue
    _p_bg = pump_once

    def _bg_pump() -> None:
        _dlog("bg_pump: thread started")
        _iter = 0
        while _started and _q_bg is not None:
            _iter += 1
            try:
                _n = _p_bg(_q_bg)
                if _n:
                    _dlog(f"bg_pump: processed {_n}")
            except Exception as _e:
                _dlog(f"bg_pump: pump_once raised {_e}")
            if _iter % 100 == 0:  # every 20 s
                _dlog(f"bg_pump: alive iter={_iter} qsize={_q_bg.size if _q_bg else '?'}")
            _time.sleep(0.2)
        _dlog("bg_pump: thread exiting")

    _threading.Thread(target=_bg_pump, daemon=True, name="allplan-pump-bg").start()
    _dlog("bridge.bg_pump_thread started")


def stop_bridge() -> None:
    global _queue, _listener, _timer, _transport_addr, _started
    if not _started:
        return

    if _timer is not None:
        with contextlib.suppress(Exception):
            _timer.stop()
        _timer = None

    if _listener is not None:
        with contextlib.suppress(Exception):
            _listener.stop()
        _listener = None

    _queue = None
    _transport_addr = None
    _started = False
    _log.info("bridge.stopped")


def get_status() -> dict[str, Any]:
    return {
        "running": _started,
        "transport": _transport_addr or "—",
        "queue_depth": _queue.size if _queue is not None else 0,
    }


# ---------------------------------------------------------------------------
# Allplan 2026 PythonPart hooks
# ---------------------------------------------------------------------------


def check_allplan_version(_build_ele: Any, _version: str) -> bool:
    return True


def create_interactor(
    coord_input: Any,
    _pyp_path: str,
    _show_pal_close_btn: Any,
    _str_table_service: Any,
    build_ele_list: list[Any],
    build_ele_composite: Any,
    control_props_list: list[Any],
    _modify_uuid_list: list[Any],
) -> McpBridgeInteractor:
    return McpBridgeInteractor(coord_input, build_ele_list, build_ele_composite, control_props_list)


class McpBridgeInteractor:
    """Persistent Allplan 2026 interactor that hosts the MCP bridge listener."""

    def __init__(
        self,
        coord_input: Any,
        build_ele_list: list[Any],
        build_ele_composite: Any,
        control_props_list: list[Any],
    ) -> None:
        # Import set_coord_input from the freshly-loaded module after start_bridge()
        # purges sys.modules — do NOT use the module-level import binding.
        _dlog("McpBridgeInteractor.__init__: calling start_bridge")
        start_bridge()
        from allplan_agent.handlers._allplan import set_coord_input as _set_ci  # noqa: PLC0415
        _set_ci(coord_input)
        _dlog("McpBridgeInteractor.__init__: coord_input set, bridge ready")

        self._palette_service: Any = None
        try:
            from BuildingElementPaletteService import (  # type: ignore[import-not-found]
                BuildingElementPaletteService,
            )

            self._palette_service = BuildingElementPaletteService(
                build_ele_list, build_ele_composite, None, control_props_list, ""
            )
            self._palette_service.show_palette("Allplan MCP Bridge")
        except Exception as exc:
            _log.debug("bridge.palette_skip error=%s", exc)

    def on_cancel_function(self) -> bool:
        with contextlib.suppress(Exception):
            from allplan_agent.handlers._allplan import set_coord_input as _set_ci  # noqa: PLC0415
            _set_ci(None)
        if self._palette_service is not None:
            with contextlib.suppress(Exception):
                self._palette_service.close_palette()
        stop_bridge()
        return True

    def on_preview_draw(self) -> None:
        if _queue is not None:
            pump_once(_queue)
        # _insert_pending intentionally NOT called here — on_preview_draw is for
        # DrawElementPreview (temporary preview), not CreateElements (permanent
        # insert). Permanent insertion needs the document context from a user
        # input event; see process_mouse_msg.

    def on_mouse_leave(self) -> None:
        if _queue is not None:
            pump_once(_queue)

    def process_mouse_msg(self, _mouse_msg: Any, _pnt: Any, _msg_info: Any) -> bool:
        if _queue is not None:
            pump_once(_queue)
        self._insert_pending()
        return True

    def _insert_pending(self) -> None:
        """Build and insert queued element specs via BaseElements.CreateElements.

        Must be called from an IFW callback (on_preview_draw, process_mouse_msg,
        on_mouse_leave) — only those calls have a valid GetInputViewDocument() context.
        Handlers queue plain WallSpec/etc. objects (zero Allplan API calls) and this
        method constructs the actual Allplan objects inside the IFW callback.
        """
        try:
            from allplan_agent.handlers._allplan import (  # noqa: PLC0415
                AllplanGeo,
                BaseElements,
                flush_pending_specs,
                get_coord_input,
            )
            specs = flush_pending_specs()
            if not specs:
                return
            _dlog(f"_insert_pending: {len(specs)} spec(s) to build")
            if BaseElements is None:
                _log.error("bridge._insert_pending: NemAll_Python_BaseElements not available")
                _dlog("_insert_pending: BaseElements is None — abort")
                return
            coord_input = get_coord_input()
            if coord_input is None:
                _log.warning("bridge._insert_pending: coord_input is None")
                _dlog("_insert_pending: coord_input is None — abort")
                return

            model_ele_list = []
            for kind, spec in specs:
                try:
                    _dlog(f"_insert_pending: building kind={kind}")
                    if kind == "wall":
                        from allplan_agent.handlers.geometry import (
                            build_wall_element,  # noqa: PLC0415
                        )
                        elem = build_wall_element(spec)
                        model_ele_list.append(elem)
                        _dlog("_insert_pending: wall element built OK")
                    elif kind == "column":
                        from allplan_agent.handlers.geometry import (
                            build_column_element,  # noqa: PLC0415
                        )
                        elem = build_column_element(spec)
                        model_ele_list.append(elem)
                        _dlog("_insert_pending: column element built OK")
                    else:
                        _log.warning("bridge._insert_pending: unknown spec kind %r", kind)
                except Exception as exc:
                    _log.error("bridge._insert_pending: build %s failed: %s", kind, exc)
                    _dlog(f"_insert_pending: build {kind} FAILED: {exc}")

            if model_ele_list:
                _dlog("_insert_pending: calling GetInputViewDocument")
                doc = coord_input.GetInputViewDocument()
                doc_type = type(doc).__name__
                doc_repr = repr(doc)[:120]
                _dlog(f"_insert_pending: doc type={doc_type} repr={doc_repr}")
                if doc is None:
                    _dlog("_insert_pending: doc is None — abort")
                    return
                _dlog("_insert_pending: calling BaseElements.CreateElements")
                BaseElements.CreateElements(doc, AllplanGeo.Matrix3D(), model_ele_list, [], None)
                _log.info("bridge._insert_pending inserted=%d", len(model_ele_list))
                _dlog(f"_insert_pending: inserted {len(model_ele_list)} element(s) OK")
        except Exception as exc:
            _log.error("bridge._insert_pending failed: %s", exc)
            _dlog(f"_insert_pending: EXCEPTION {exc}")

    def CreateElements(
        self,
        _build_ele: Any,
        _matrix: Any,
        model_ele_list: list[Any],
        handles: list[Any],
        _input_pnt: Any = None,
    ) -> tuple[list[Any], list[Any]]:
        """Pass-through required by IFW.CreateElements dispatch."""
        return model_ele_list, handles

    def modify_element_property(self, _page: int, _name: str, _value: Any) -> None:
        pass
