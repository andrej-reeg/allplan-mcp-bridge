"""Attribute tools: get and set element attributes."""

from typing import Any

from ..models.attributes import AttributeSpec
from ..models.references import ElementKind
from ..server import get_client, get_settings, mcp


@mcp.tool()
async def get_attributes(uuid: str, kind: ElementKind) -> dict[str, Any]:
    """Return all scalar attributes of an element."""
    s = get_settings()
    return await get_client().call(
        "get_attributes", {"uuid": uuid, "kind": kind}, timeout=s.request_timeout_seconds
    )


@mcp.tool()
async def set_attributes(
    uuid: str,
    kind: ElementKind,
    attributes: list[AttributeSpec],
) -> dict[str, Any]:
    """Set one or more attributes on an element. Participates in undo."""
    args: dict[str, Any] = {
        "uuid": uuid,
        "kind": kind,
        "attributes": [a.model_dump(mode="json") for a in attributes],
    }
    s = get_settings()
    return await get_client().call(
        "set_attributes", args, timeout=s.request_timeout_seconds
    )
