"""Grid definition models. Coordinates in millimetres."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GridLine(BaseModel):
    """A single named grid line with its coordinate along the perpendicular axis."""

    name: str = Field(min_length=1, max_length=64)
    coordinate_mm: float


class GridDefinition(BaseModel):
    """Named axis grid used as a coordinate reference system.

    x_lines: vertical lines (have X coordinates, span in Y direction).
    y_lines: horizontal lines (have Y coordinates, span in X direction).
    z_base_mm: default floor elevation for elements placed on this grid.
    """

    name: str = Field(min_length=1, max_length=128)
    x_lines: list[GridLine] = Field(default_factory=list)
    y_lines: list[GridLine] = Field(default_factory=list)
    z_base_mm: float = 0.0
    description: str = ""

    def x_line(self, line_name: str) -> GridLine:
        """Return the X grid line with the given name. Raises KeyError if absent."""
        for gl in self.x_lines:
            if gl.name == line_name:
                return gl
        raise KeyError(f"X grid line {line_name!r} not found in grid {self.name!r}")

    def y_line(self, line_name: str) -> GridLine:
        """Return the Y grid line with the given name. Raises KeyError if absent."""
        for gl in self.y_lines:
            if gl.name == line_name:
                return gl
        raise KeyError(f"Y grid line {line_name!r} not found in grid {self.name!r}")
