"""IFC tools: export and import IFC files."""

from typing import Any

from ..server import get_client, get_settings, mcp


@mcp.tool()
async def export_ifc(
    path: str,
    schema_version: str = "IFC4",
    element_uuids: list[str] | None = None,
) -> dict[str, Any]:
    """Export model or selected elements to an IFC file. Path must be absolute, inside workspace."""
    args: dict[str, Any] = {"path": path, "schema_version": schema_version}
    if element_uuids is not None:
        args["elements"] = [{"uuid": u, "kind": "unknown"} for u in element_uuids]
    s = get_settings()
    return await get_client().call("export_ifc", args, timeout=s.long_op_timeout_seconds)


@mcp.tool()
async def import_ifc(path: str) -> dict[str, Any]:
    """Import an IFC file into the active document. Path must be absolute, inside workspace."""
    s = get_settings()
    return await get_client().call(
        "import_ifc", {"path": path}, timeout=s.long_op_timeout_seconds
    )
