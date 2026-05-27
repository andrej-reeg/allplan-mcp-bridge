"""In-memory cache mapping element UUID → creation spec.

Used by copy_to_grid_position to re-create elements at new coordinates.
Cache is lost on server restart — this is intentional (v1 scope).
"""

from __future__ import annotations

import copy
from typing import Any

# uuid → {"kind": str, "spec": dict[str, Any]}
_cache: dict[str, dict[str, Any]] = {}


def store(uuid: str, kind: str, spec: dict[str, Any]) -> None:
    _cache[uuid] = {"kind": kind, "spec": copy.deepcopy(spec)}


def lookup(uuid: str) -> dict[str, Any] | None:
    return _cache.get(uuid)


def _shift_point(pt: dict[str, Any], dx: float, dy: float, dz: float) -> dict[str, Any]:
    return {
        "x": float(pt.get("x", 0.0)) + dx,
        "y": float(pt.get("y", 0.0)) + dy,
        "z": float(pt.get("z", 0.0)) + dz,
    }


def offset_spec(kind: str, spec: dict[str, Any], dx: float, dy: float, dz: float) -> dict[str, Any]:
    """Return a copy of spec with all coordinate fields shifted by (dx, dy, dz)."""
    s = copy.deepcopy(spec)
    if kind in ("wall", "beam"):
        s["start"] = _shift_point(s["start"], dx, dy, dz)
        s["end"] = _shift_point(s["end"], dx, dy, dz)
    elif kind == "column":
        s["base"] = _shift_point(s["base"], dx, dy, dz)
    elif kind == "slab":
        s["outline"] = [_shift_point(pt, dx, dy, dz) for pt in s["outline"]]
    return s
