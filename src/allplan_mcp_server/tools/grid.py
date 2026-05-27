"""Grid tools: define, query, and use named axis grids for element positioning."""

from __future__ import annotations

from typing import Any

from .. import element_cache, grid_store
from ..models.grid import GridDefinition, GridLine
from ..server import get_client, get_settings, mcp


@mcp.tool()
async def define_grid(
    name: str,
    x_lines: list[GridLine],
    y_lines: list[GridLine],
    z_base_mm: float = 0.0,
    description: str = "",
) -> dict[str, Any]:
    """Store or overwrite a named grid definition.

    x_lines: lines with X coordinates (vertical, parallel to the Y axis).
    y_lines: lines with Y coordinates (horizontal, parallel to the X axis).
    Each line has a name (e.g. "28", "A") and a coordinate_mm value.
    Units: mm. Call get_grid_lines to verify after defining.
    """
    defn = GridDefinition(
        name=name,
        x_lines=x_lines,
        y_lines=y_lines,
        z_base_mm=z_base_mm,
        description=description,
    )
    grid_store.put_grid(defn)
    return {
        "defined": True,
        "name": name,
        "x_count": len(x_lines),
        "y_count": len(y_lines),
        "z_base_mm": z_base_mm,
    }


@mcp.tool()
async def list_grids() -> dict[str, Any]:
    """Return a summary of all defined grids.

    To get full line data for a specific grid, call get_grid_lines.
    """
    grids = grid_store.list_grids()
    return {
        "grids": [
            {
                "name": g.name,
                "x_count": len(g.x_lines),
                "y_count": len(g.y_lines),
                "z_base_mm": g.z_base_mm,
                "description": g.description,
            }
            for g in grids
        ]
    }


@mcp.tool()
async def get_grid_lines(grid_name: str) -> dict[str, Any]:
    """Return all grid line names and coordinates for a named grid.

    Use this to resolve grid line names to mm coordinates before
    calling create_wall, create_column, or other placement tools.
    Example: X line "28" → coordinate_mm=28000 means x=28000 mm.
    """
    try:
        g = grid_store.get_grid(grid_name)
    except KeyError as exc:
        return {"error": str(exc)}
    return {
        "name": g.name,
        "z_base_mm": g.z_base_mm,
        "x_lines": [{"name": gl.name, "coordinate_mm": gl.coordinate_mm} for gl in g.x_lines],
        "y_lines": [{"name": gl.name, "coordinate_mm": gl.coordinate_mm} for gl in g.y_lines],
    }


@mcp.tool()
async def delete_grid(grid_name: str) -> dict[str, Any]:
    """Remove a grid definition by name."""
    try:
        grid_store.delete_grid(grid_name)
    except KeyError as exc:
        return {"error": str(exc)}
    return {"deleted": True, "name": grid_name}


@mcp.tool()
async def copy_to_grid_position(
    element_uuids: list[str],
    grid_name: str,
    from_x_line: str | None = None,
    to_x_line: str | None = None,
    from_y_line: str | None = None,
    to_y_line: str | None = None,
) -> dict[str, Any]:
    """Copy one or more elements to a new grid position.

    Computes the offset from (from_x_line → to_x_line) and/or
    (from_y_line → to_y_line), then re-creates each element at the
    offset position. Elements must have been created in this session
    (UUIDs are looked up in the in-memory spec cache).

    Example: copy a column from between X28–X29 to between X30–X31:
      from_x_line="28", to_x_line="30"  →  dx = X30 - X28

    Returns a list of new ElementRef objects for the created copies.
    """
    try:
        g = grid_store.get_grid(grid_name)
    except KeyError as exc:
        return {"error": str(exc)}

    dx = 0.0
    dy = 0.0
    if from_x_line and to_x_line:
        dx = g.x_line(to_x_line).coordinate_mm - g.x_line(from_x_line).coordinate_mm
    if from_y_line and to_y_line:
        dy = g.y_line(to_y_line).coordinate_mm - g.y_line(from_y_line).coordinate_mm

    if dx == 0.0 and dy == 0.0:
        return {"error": "No offset: provide from_x_line+to_x_line or from_y_line+to_y_line."}

    s = get_settings()
    new_refs: list[dict[str, Any]] = []
    skipped: list[str] = []

    for uuid in element_uuids:
        cached = element_cache.lookup(uuid)
        if cached is None:
            skipped.append(uuid)
            continue
        kind = cached["kind"]
        adjusted_spec = element_cache.offset_spec(kind, cached["spec"], dx, dy, 0.0)
        result = await get_client().call(
            f"create_{kind}", adjusted_spec, timeout=s.request_timeout_seconds
        )
        element_cache.store(result["uuid"], kind, adjusted_spec)
        new_refs.append(result)

    return {
        "copied": len(new_refs),
        "skipped": skipped,
        "dx_mm": dx,
        "dy_mm": dy,
        "elements": new_refs,
    }
