"""Geometry tools: walls, slabs, columns, beams, element CRUD."""

from typing import Any

from ..models.geometry import BeamSpec, ColumnSpec, Point3D, SlabSpec, WallSpec
from ..models.references import ElementKind
from ..server import get_client, get_settings, mcp


@mcp.tool()
async def create_wall(
    start: Point3D,
    end: Point3D,
    height_mm: float,
    thickness_mm: float,
    layer: str | None = None,
    axis_offset_mm: float = 0.0,
) -> dict[str, Any]:
    """Create a wall element in the active Allplan document. Units: mm. Participates in undo."""
    spec = WallSpec(
        start=start,
        end=end,
        height_mm=height_mm,
        thickness_mm=thickness_mm,
        layer=layer,
        axis_offset_mm=axis_offset_mm,
    )
    s = get_settings()
    return await get_client().call(
        "create_wall", spec.model_dump(mode="json"), timeout=s.request_timeout_seconds
    )


@mcp.tool()
async def create_slab(
    outline: list[Point3D],
    thickness_mm: float,
    layer: str | None = None,
) -> dict[str, Any]:
    """Create a slab element from a polygon outline. Minimum 3 points. Units: mm."""
    spec = SlabSpec(outline=outline, thickness_mm=thickness_mm, layer=layer)
    s = get_settings()
    return await get_client().call(
        "create_slab", spec.model_dump(mode="json"), timeout=s.request_timeout_seconds
    )


@mcp.tool()
async def create_column(
    base: Point3D,
    height_mm: float,
    width_mm: float,
    depth_mm: float,
    layer: str | None = None,
) -> dict[str, Any]:
    """Create a rectangular column element. Units: mm."""
    spec = ColumnSpec(
        base=base,
        height_mm=height_mm,
        width_mm=width_mm,
        depth_mm=depth_mm,
        layer=layer,
    )
    s = get_settings()
    return await get_client().call(
        "create_column", spec.model_dump(mode="json"), timeout=s.request_timeout_seconds
    )


@mcp.tool()
async def create_beam(
    start: Point3D,
    end: Point3D,
    width_mm: float,
    height_mm: float,
    layer: str | None = None,
) -> dict[str, Any]:
    """Create a beam element between two points. Units: mm."""
    spec = BeamSpec(
        start=start,
        end=end,
        width_mm=width_mm,
        height_mm=height_mm,
        layer=layer,
    )
    s = get_settings()
    return await get_client().call(
        "create_beam", spec.model_dump(mode="json"), timeout=s.request_timeout_seconds
    )


@mcp.tool()
async def get_element(uuid: str, kind: ElementKind) -> dict[str, Any]:
    """Retrieve an element by UUID. Raises if not found."""
    s = get_settings()
    return await get_client().call(
        "get_element", {"uuid": uuid, "kind": kind}, timeout=s.request_timeout_seconds
    )


@mcp.tool()
async def delete_element(uuid: str, kind: ElementKind) -> dict[str, Any]:
    """Delete an element by UUID. Participates in undo."""
    s = get_settings()
    return await get_client().call(
        "delete_element", {"uuid": uuid, "kind": kind}, timeout=s.request_timeout_seconds
    )


@mcp.tool()
async def move_element(
    uuid: str,
    kind: ElementKind,
    dx: float,
    dy: float,
    dz: float,
) -> dict[str, Any]:
    """Translate an element by (dx, dy, dz) mm. Participates in undo."""
    s = get_settings()
    return await get_client().call(
        "move_element",
        {"uuid": uuid, "kind": kind, "dx": dx, "dy": dy, "dz": dz},
        timeout=s.request_timeout_seconds,
    )
