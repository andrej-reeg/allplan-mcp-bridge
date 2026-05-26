"""Stand-in for NemAll_Python_* Allplan modules during unit and integration tests.

Imported automatically by allplan_agent/handlers/_allplan.py when the real
Allplan modules are not available (i.e., outside Allplan's embedded Python).
"""

import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Fake NemAll_Python_Geometry
# ---------------------------------------------------------------------------

class Point3D:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x = x
        self.y = y
        self.z = z

    def __repr__(self) -> str:
        return f"Point3D({self.x}, {self.y}, {self.z})"


class Vector3D:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> None:
        self.x = x
        self.y = y
        self.z = z


# ---------------------------------------------------------------------------
# Fake NemAll_Python_BasisElements
# ---------------------------------------------------------------------------

class _FakeElement:
    """Minimal element returned by create_* functions."""

    def __init__(self, kind: str, **kwargs: Any) -> None:
        self.uuid = str(uuid.uuid4())
        self.kind = kind
        self._attrs: dict[str, Any] = dict(kwargs)

    def get_attribute(self, name: str) -> Any:
        return self._attrs.get(name)

    def set_attribute(self, name: str, value: Any) -> None:
        self._attrs[name] = value


# Registry of created elements — cleared between tests via reset_state()
_elements: dict[str, _FakeElement] = {}


def reset_state() -> None:
    """Clear all fake elements. Call in test teardown."""
    _elements.clear()


def create_wall(
    start: Point3D,
    end: Point3D,
    height_mm: float,
    thickness_mm: float,
    layer: str | None = None,
) -> _FakeElement:
    elem = _FakeElement("wall", start=start, end=end, height_mm=height_mm,
                        thickness_mm=thickness_mm, layer=layer)
    _elements[elem.uuid] = elem
    return elem


def create_slab(
    outline: list[Point3D],
    thickness_mm: float,
    layer: str | None = None,
) -> _FakeElement:
    elem = _FakeElement("slab", outline=outline, thickness_mm=thickness_mm, layer=layer)
    _elements[elem.uuid] = elem
    return elem


def get_element(elem_uuid: str) -> _FakeElement | None:
    return _elements.get(elem_uuid)


def delete_element(elem_uuid: str) -> bool:
    return _elements.pop(elem_uuid, None) is not None


# ---------------------------------------------------------------------------
# Fake NemAll_Python_AllplanSettings (layer service)
# ---------------------------------------------------------------------------

_layers: dict[str, dict[str, Any]] = {}


def reset_layers() -> None:
    _layers.clear()


def list_layers() -> list[dict[str, Any]]:
    return list(_layers.values())


def create_layer(name: str, parent: str | None = None,
                 visible: bool = True, locked: bool = False) -> dict[str, Any]:
    layer = {"name": name, "parent": parent, "visible": visible, "locked": locked}
    _layers[name] = layer
    return layer


def get_layer(name: str) -> dict[str, Any] | None:
    return _layers.get(name)
