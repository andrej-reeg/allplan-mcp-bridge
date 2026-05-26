"""Document tools: info, save, undo, redo."""

from typing import Any

from ..server import get_client, get_settings, mcp


@mcp.tool()
async def get_active_document_info() -> dict[str, Any]:
    """Return name, path, and units of the active Allplan document."""
    s = get_settings()
    return await get_client().call(
        "get_active_document_info", {}, timeout=s.request_timeout_seconds
    )


@mcp.tool()
async def save_document() -> dict[str, Any]:
    """Save the active Allplan document to disk."""
    s = get_settings()
    return await get_client().call("save_document", {}, timeout=s.long_op_timeout_seconds)


@mcp.tool()
async def undo() -> dict[str, Any]:
    """Undo the last operation in the active Allplan document."""
    s = get_settings()
    return await get_client().call("undo", {}, timeout=s.request_timeout_seconds)


@mcp.tool()
async def redo() -> dict[str, Any]:
    """Redo the last undone operation in the active Allplan document."""
    s = get_settings()
    return await get_client().call("redo", {}, timeout=s.request_timeout_seconds)
