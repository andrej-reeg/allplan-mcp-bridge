"""Layer tools: list, create, set visibility, assign to element."""

from typing import Any

from ..models.references import ElementKind
from ..server import get_client, get_settings, mcp


@mcp.tool()
async def list_layers() -> dict[str, Any]:
    """Return all layers defined in the active Allplan document."""
    s = get_settings()
    return await get_client().call("list_layers", {}, timeout=s.request_timeout_seconds)


@mcp.tool()
async def create_layer(
    name: str,
    parent: str | None = None,
    visible: bool = True,
    locked: bool = False,
) -> dict[str, Any]:
    """Create a new layer. Returns the created layer dict."""
    args: dict[str, Any] = {
        "name": name,
        "parent": parent,
        "visible": visible,
        "locked": locked,
    }
    s = get_settings()
    return await get_client().call("create_layer", args, timeout=s.request_timeout_seconds)


@mcp.tool()
async def set_layer_visibility(name: str, visible: bool) -> dict[str, Any]:
    """Show or hide a layer by name."""
    s = get_settings()
    return await get_client().call(
        "set_layer_visibility",
        {"name": name, "visible": visible},
        timeout=s.request_timeout_seconds,
    )


@mcp.tool()
async def assign_layer(uuid: str, kind: ElementKind, layer: str) -> dict[str, Any]:
    """Assign an element to a layer by name. Participates in undo."""
    s = get_settings()
    return await get_client().call(
        "assign_layer",
        {"uuid": uuid, "kind": kind, "layer": layer},
        timeout=s.request_timeout_seconds,
    )
