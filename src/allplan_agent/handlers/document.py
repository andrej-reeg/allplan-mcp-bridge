"""Document handlers: info, save, undo, redo; also ping."""

import contextlib
import logging
import time
from typing import Any

from ..dispatcher import command
from ..errors import AllplanApiError
from ._allplan import AllplanElements

_log = logging.getLogger(__name__)


@command("ping")
def handle_ping(args: dict[str, Any]) -> dict[str, Any]:
    return {"pong": True, "t": time.monotonic()}


@command("get_active_document_info")
def handle_get_active_document_info(args: dict[str, Any]) -> dict[str, Any]:
    import threading as _t
    # Allplan API calls require main-thread context. The bg_pump thread calls this
    # from a background thread, so we return a safe stub to avoid deadlocking.
    if _t.current_thread() is not _t.main_thread():
        return {"main_thread_required": True}

    get_fn = getattr(AllplanElements, "get_active_document_info", None)
    if get_fn is not None:
        try:
            return dict(get_fn())
        except Exception as exc:
            raise AllplanApiError(f"get_active_document_info failed: {exc}", exc) from exc

    info: dict[str, Any] = {}
    for attr in ("GetActiveDrawingFileNumber", "GetActiveLayoutNumber"):
        fn = getattr(AllplanElements, attr, None)
        if fn is not None:
            with contextlib.suppress(Exception):
                info[attr] = fn()
    return info


def _require_main_thread(cmd: str) -> None:
    import threading as _t
    if _t.current_thread() is not _t.main_thread():
        raise AllplanApiError(
            f"{cmd} requires main-thread context (not available on bg_pump thread)",
            None,
        )


@command("save_document")
def handle_save_document(args: dict[str, Any]) -> dict[str, Any]:
    _require_main_thread("save_document")
    try:
        ok = AllplanElements.save_document()
    except Exception as exc:
        raise AllplanApiError(f"save_document failed: {exc}", exc) from exc
    _log.info("document.save ok=%s", ok)
    return {"saved": bool(ok)}


@command("undo")
def handle_undo(args: dict[str, Any]) -> dict[str, Any]:
    _require_main_thread("undo")
    try:
        ok = AllplanElements.undo()
    except Exception as exc:
        raise AllplanApiError(f"undo failed: {exc}", exc) from exc
    return {"ok": bool(ok)}


@command("redo")
def handle_redo(args: dict[str, Any]) -> dict[str, Any]:
    _require_main_thread("redo")
    try:
        ok = AllplanElements.redo()
    except Exception as exc:
        raise AllplanApiError(f"redo failed: {exc}", exc) from exc
    return {"ok": bool(ok)}
