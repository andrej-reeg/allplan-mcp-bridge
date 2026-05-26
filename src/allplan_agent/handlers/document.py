"""Document handlers: info, save, undo, redo."""

import logging
from typing import Any

from ..dispatcher import command
from ..errors import AllplanApiError
from ._allplan import AllplanElements

_log = logging.getLogger(__name__)


@command("get_active_document_info")
def handle_get_active_document_info(args: dict[str, Any]) -> dict[str, Any]:
    try:
        info = AllplanElements.get_active_document_info()
    except Exception as exc:
        raise AllplanApiError(f"get_active_document_info failed: {exc}", exc) from exc
    return dict(info)


@command("save_document")
def handle_save_document(args: dict[str, Any]) -> dict[str, Any]:
    try:
        ok = AllplanElements.save_document()
    except Exception as exc:
        raise AllplanApiError(f"save_document failed: {exc}", exc) from exc
    _log.info("document.save ok=%s", ok)
    return {"saved": bool(ok)}


@command("undo")
def handle_undo(args: dict[str, Any]) -> dict[str, Any]:
    try:
        ok = AllplanElements.undo()
    except Exception as exc:
        raise AllplanApiError(f"undo failed: {exc}", exc) from exc
    return {"ok": bool(ok)}


@command("redo")
def handle_redo(args: dict[str, Any]) -> dict[str, Any]:
    try:
        ok = AllplanElements.redo()
    except Exception as exc:
        raise AllplanApiError(f"redo failed: {exc}", exc) from exc
    return {"ok": bool(ok)}
