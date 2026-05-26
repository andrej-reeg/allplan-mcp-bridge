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


def create_column(
    base: Point3D,
    height_mm: float,
    width_mm: float,
    depth_mm: float,
    layer: str | None = None,
) -> _FakeElement:
    elem = _FakeElement("column", base=base, height_mm=height_mm,
                        width_mm=width_mm, depth_mm=depth_mm, layer=layer)
    _elements[elem.uuid] = elem
    return elem


def create_beam(
    start: Point3D,
    end: Point3D,
    width_mm: float,
    height_mm: float,
    layer: str | None = None,
) -> _FakeElement:
    elem = _FakeElement("beam", start=start, end=end,
                        width_mm=width_mm, height_mm=height_mm, layer=layer)
    _elements[elem.uuid] = elem
    return elem


def get_element(elem_uuid: str) -> _FakeElement | None:
    return _elements.get(elem_uuid)


def delete_element(elem_uuid: str) -> bool:
    return _elements.pop(elem_uuid, None) is not None


def move_element(elem_uuid: str, dx: float, dy: float, dz: float) -> bool:
    elem = _elements.get(elem_uuid)
    if elem is None:
        return False
    elem._attrs["moved_by"] = (dx, dy, dz)
    return True


# ---------------------------------------------------------------------------
# Fake document state
# ---------------------------------------------------------------------------

_doc_name: str = "fake_document.ndw"
_doc_path: str = "/fake/workspace/fake_document.ndw"
_undo_stack: list[str] = []
_redo_stack: list[str] = []
_saved: bool = True


def reset_document() -> None:
    global _doc_name, _doc_path, _saved
    _doc_name = "fake_document.ndw"
    _doc_path = "/fake/workspace/fake_document.ndw"
    _undo_stack.clear()
    _redo_stack.clear()
    _saved = True


def get_active_document_info() -> dict[str, Any]:
    return {"name": _doc_name, "path": _doc_path, "units": "mm"}


def save_document() -> bool:
    global _saved
    _saved = True
    return True


def BeginUndoBracket(name: str) -> None:  # noqa: N802
    _undo_stack.append(name)


def CommitUndoBracket(name: str) -> None:  # noqa: N802
    pass


def RollbackUndoBracket(name: str) -> None:  # noqa: N802
    if _undo_stack:
        _undo_stack.pop()


def undo() -> bool:
    return True


def redo() -> bool:
    return True


# ---------------------------------------------------------------------------
# Fake IFC
# ---------------------------------------------------------------------------

_ifc_exports: list[str] = []
_ifc_imports: list[str] = []


def reset_ifc() -> None:
    _ifc_exports.clear()
    _ifc_imports.clear()


def export_ifc(path: str, schema: str = "IFC4",
               element_uuids: list[str] | None = None) -> bool:
    _ifc_exports.append(path)
    return True


def import_ifc(path: str) -> list[_FakeElement]:
    _ifc_imports.append(path)
    elem = _FakeElement("unknown")
    _elements[elem.uuid] = elem
    return [elem]


def reset_all() -> None:
    """Reset all fake state. Call in test fixtures."""
    reset_state()
    reset_layers()
    reset_document()
    reset_ifc()


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
