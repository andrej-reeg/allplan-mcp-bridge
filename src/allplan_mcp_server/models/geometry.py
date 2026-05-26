"""Geometry models. All lengths are in millimetres unless stated otherwise."""

import math
from typing import Annotated

from pydantic import BaseModel, Field, model_validator

# Allplan's practical upper limit for element dimensions.
# A wall longer than this (10 km) is almost certainly a data error.
_MAX_EXTENT_MM: float = 10_000_000.0  # 10 km


def _finite(v: float) -> float:
    if not math.isfinite(v):
        raise ValueError("coordinate must be finite (no NaN or Inf)")
    return v


_Coord = Annotated[float, Field(strict=False)]


class Point3D(BaseModel):
    """A point in 3D space. Units: millimetres."""

    x: _Coord
    y: _Coord
    z: _Coord

    @model_validator(mode="after")
    def _finite_coords(self) -> "Point3D":
        _finite(self.x)
        _finite(self.y)
        _finite(self.z)
        return self

    def distance_to(self, other: "Point3D") -> float:
        return math.sqrt(
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )


class Vector3D(BaseModel):
    """A direction vector. Units: millimetres."""

    x: _Coord
    y: _Coord
    z: _Coord

    @model_validator(mode="after")
    def _finite_coords(self) -> "Vector3D":
        _finite(self.x)
        _finite(self.y)
        _finite(self.z)
        return self


class WallSpec(BaseModel):
    """Specification for creating a wall element.

    Units: millimetres.
    Side effects: creates a wall in the active Allplan document.
    Participates in undo.
    """

    start: Point3D
    end: Point3D
    height_mm: float = Field(gt=0, le=_MAX_EXTENT_MM)
    thickness_mm: float = Field(gt=0, le=_MAX_EXTENT_MM)
    layer: str | None = None
    axis_offset_mm: float = Field(default=0.0)

    @model_validator(mode="after")
    def _non_degenerate(self) -> "WallSpec":
        if self.start.distance_to(self.end) < 1.0:
            raise ValueError(
                "start and end must be at least 1 mm apart (degenerate wall)"
            )
        dist = self.start.distance_to(self.end)
        if dist > _MAX_EXTENT_MM:
            raise ValueError(
                f"wall length {dist:.0f} mm exceeds maximum {_MAX_EXTENT_MM:.0f} mm"
            )
        return self


class SlabSpec(BaseModel):
    """Specification for creating a slab element.

    Units: millimetres.
    Side effects: creates a slab in the active Allplan document.
    Participates in undo.
    """

    outline: list[Point3D] = Field(min_length=3)
    thickness_mm: float = Field(gt=0, le=_MAX_EXTENT_MM)
    layer: str | None = None


class ColumnSpec(BaseModel):
    """Specification for creating a column element.

    Units: millimetres.
    Side effects: creates a column in the active Allplan document.
    Participates in undo.
    """

    base: Point3D
    height_mm: float = Field(gt=0, le=_MAX_EXTENT_MM)
    width_mm: float = Field(gt=0, le=_MAX_EXTENT_MM)
    depth_mm: float = Field(gt=0, le=_MAX_EXTENT_MM)
    layer: str | None = None


class BeamSpec(BaseModel):
    """Specification for creating a beam element.

    Units: millimetres.
    Side effects: creates a beam in the active Allplan document.
    Participates in undo.
    """

    start: Point3D
    end: Point3D
    width_mm: float = Field(gt=0, le=_MAX_EXTENT_MM)
    height_mm: float = Field(gt=0, le=_MAX_EXTENT_MM)
    layer: str | None = None

    @model_validator(mode="after")
    def _non_degenerate(self) -> "BeamSpec":
        if self.start.distance_to(self.end) < 1.0:
            raise ValueError(
                "start and end must be at least 1 mm apart (degenerate beam)"
            )
        return self


class GenericSolidSpec(BaseModel):
    """Specification for a closed polyhedron from explicit vertices and faces.

    Units: millimetres.
    Each face is a list of vertex indices (into the vertices list).
    Minimum 4 vertices and 4 faces to form a tetrahedron.
    Side effects: creates a generic solid in the active Allplan document.
    Participates in undo.
    """

    vertices: list[Point3D] = Field(min_length=4)
    faces: list[list[int]] = Field(min_length=4)
    layer: str | None = None

    @model_validator(mode="after")
    def _valid_face_indices(self) -> "GenericSolidSpec":
        n = len(self.vertices)
        for face in self.faces:
            if len(face) < 3:
                raise ValueError("each face must have at least 3 vertex indices")
            for idx in face:
                if idx < 0 or idx >= n:
                    raise ValueError(
                        f"face index {idx} out of range [0, {n - 1}]"
                    )
        return self
