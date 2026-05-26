"""IFC import/export handlers. Paths validated against workspace root."""

import logging
from pathlib import Path
from typing import Any

from allplan_mcp_server.models.ifc import (
    IFC_HARD_LIMIT_BYTES,
    IFC_WARN_BYTES,
    IfcExportSpec,
    IfcImportSpec,
)
from allplan_mcp_server.models.references import ElementRef
from allplan_mcp_server.security import PathNotAllowedError, check_ifc_export_size, validate_path

from ..dispatcher import command
from ..errors import AllplanApiError
from ._allplan import AllplanElements

_log = logging.getLogger(__name__)

# Workspace root injected at agent startup. None → path validation skipped
# (only acceptable in unit tests; enforced in production via agent init).
_workspace_root: Path | None = None


def set_workspace_root(root: Path) -> None:
    global _workspace_root
    _workspace_root = root


def _check_path(path: Path) -> Path:
    if _workspace_root is None:
        return path
    return validate_path(path, _workspace_root)


@command("export_ifc")
def handle_export_ifc(args: dict[str, Any]) -> dict[str, Any]:
    spec = IfcExportSpec.model_validate(args)
    try:
        safe_path = _check_path(spec.path)
    except PathNotAllowedError as exc:
        raise AllplanApiError(str(exc), exc) from exc

    element_uuids: list[str] | None = None
    if spec.elements is not None:
        element_uuids = [e.uuid for e in spec.elements]

    try:
        ok = AllplanElements.export_ifc(
            path=str(safe_path),
            schema=spec.schema_version,
            element_uuids=element_uuids,
        )
    except Exception as exc:
        raise AllplanApiError(f"export_ifc failed: {exc}", exc) from exc

    try:
        oversized = check_ifc_export_size(safe_path, IFC_WARN_BYTES, IFC_HARD_LIMIT_BYTES)
    except ValueError as exc:
        raise AllplanApiError(str(exc), exc) from exc
    if oversized:
        _log.warning("ifc.export.large path=%s", safe_path.name)
    _log.info("ifc.export path=%s schema=%s", safe_path.name, spec.schema_version)
    return {"exported": bool(ok), "path": str(safe_path)}


@command("import_ifc")
def handle_import_ifc(args: dict[str, Any]) -> dict[str, Any]:
    spec = IfcImportSpec.model_validate(args)
    try:
        safe_path = _check_path(spec.path)
    except PathNotAllowedError as exc:
        raise AllplanApiError(str(exc), exc) from exc

    try:
        elements = AllplanElements.import_ifc(path=str(safe_path))
    except Exception as exc:
        raise AllplanApiError(f"import_ifc failed: {exc}", exc) from exc

    refs = [
        ElementRef(uuid=e.uuid, kind="unknown").model_dump()
        for e in elements
    ]
    _log.info("ifc.import path=%s count=%d", safe_path.name, len(refs))
    return {"imported": len(refs), "elements": refs}
