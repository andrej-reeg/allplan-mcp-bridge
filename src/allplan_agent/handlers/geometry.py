"""Geometry handlers: wall, slab, column, beam, get/delete/move element."""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from typing import Any

from allplan_mcp_server.models.geometry import (
    BeamSpec,
    ColumnSpec,
    SlabSpec,
    WallSpec,
)
from allplan_mcp_server.models.references import ElementRef

from ..dispatcher import command
from ..errors import AllplanApiError
from ._allplan import (
    _USING_FAKE,
    IFW,
    AllplanElements,
    AllplanGeo,
    ArchElements,
    BaseElements,
    queue_spec,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _common_props(layer: str | None) -> Any:
    """Build a CommonProperties object with optional layer override."""
    cls = getattr(BaseElements, "CommonProperties", None) or AllplanElements.CommonProperties
    props = cls()
    if hasattr(props, "GetGlobalProperties"):
        props.GetGlobalProperties()
    elif hasattr(props, "GetDefault"):
        props.GetDefault()
    if layer is not None and hasattr(props, "Layer"):
        props.Layer = layer
    return props


def _pt(p: Any) -> Any:
    return AllplanGeo.Point3D(p.x, p.y, p.z)


def _insert_elements(coord_input: Any, model_ele_list: list[Any]) -> None:
    """Insert elements into the active document via BaseElements.CreateElements."""
    matrix = AllplanGeo.Matrix3D()
    failures: list[str] = []

    # Correct pattern (ref: AlejoDuarte23/allplan-mcp-server-python):
    #   doc = coord_input.GetInputViewDocument()
    #   BaseElements.CreateElements(doc, matrix, elements, [], None)
    create_fn = getattr(BaseElements, "CreateElements", None) if BaseElements is not None else None
    if create_fn is not None and coord_input is not None:
        get_doc = getattr(coord_input, "GetInputViewDocument", None)
        if get_doc is not None:
            try:
                doc = get_doc()
                create_fn(doc, matrix, model_ele_list, [], None)
                _log.debug("_insert_elements: BaseElements.CreateElements OK")
                return
            except Exception as exc:
                failures.append(f"BaseElements.CreateElements: {exc}")
                _log.warning("_insert_elements: BaseElements.CreateElements failed: %s", exc)

    # Fallback: IFW.CreateElements (Allplan ≤2025)
    ifw_fn = getattr(IFW, "CreateElements", None) if IFW is not None else None
    if ifw_fn is not None and coord_input is not None:
        try:
            ifw_fn(coord_input, matrix, model_ele_list, [], None)
            _log.debug("_insert_elements: IFW.CreateElements OK")
            return
        except Exception as exc:
            failures.append(f"IFW.CreateElements: {exc}")
            _log.warning("_insert_elements: IFW.CreateElements failed: %s", exc)

    # Fallback: coord_input.CreateElements
    if coord_input is not None:
        m = getattr(coord_input, "CreateElements", None)
        if m is not None:
            try:
                m(matrix, model_ele_list, [], None)
                _log.debug("_insert_elements: coord_input.CreateElements OK")
                return
            except Exception as exc:
                failures.append(f"coord_input.CreateElements: {exc}")
                _log.warning("_insert_elements: coord_input.CreateElements failed: %s", exc)

    tried = "; ".join(failures) or "no methods found"
    raise AllplanApiError(
        f"Cannot insert elements — tried: {tried}. coord_input present: {coord_input is not None}"
    )


def _element_uuid(elem: Any) -> str:
    """Extract a string UUID from an inserted element's adapter."""
    try:
        adapter = elem.GetBaseElementAdapter()
        if adapter is None:
            return ""
        uuid_obj = adapter.GetModelElementUUID()
        if uuid_obj is None:
            return ""
        for method in ("ToGuidString", "ToString"):
            fn = getattr(uuid_obj, method, None)
            if fn:
                return str(fn())
        return str(uuid_obj)
    except Exception as exc:
        _log.debug("_element_uuid failed: %s", exc)
        return f"unk_{id(elem)}"


# ---------------------------------------------------------------------------
# Wall
# ---------------------------------------------------------------------------


def _build_wall_properties(height_mm: float, thickness_mm: float) -> Any:
    """Construct WallProperties with a single full-height tier.

    WallTierProperties cannot be constructed empty — must be copied from an
    existing tier. WallProperties() ships with one default tier at index 0.
    """
    wall_props = ArchElements.WallProperties()

    for attr in ("Height", "WallHeight"):
        if hasattr(wall_props, attr):
            setattr(wall_props, attr, float(height_mm))
            break

    tier_props = None
    for method in ("GetTier", "GetTierAt", "GetTierProperties"):
        m = getattr(wall_props, method, None)
        if m is not None:
            try:
                tier_props = m(0)
                break
            except Exception as exc:
                _log.debug("_build_wall_properties: %s(0) failed: %s", method, exc)

    if tier_props is None:
        _log.warning(
            "_build_wall_properties: could not retrieve default tier; thickness uses wall default"
        )
        return wall_props

    for attr in ("Thickness", "WallThickness"):
        if hasattr(tier_props, attr):
            setattr(tier_props, attr, float(thickness_mm))
            break

    return wall_props


def _wall_as_model_element(spec: WallSpec) -> Any:
    """Approximate wall as a positioned ModelElement3D box.

    Tries three placement strategies in order, logging each failure so the
    debug log reveals which Allplan 2026 API is available.

    APIs confirmed from NemetschekAllplan/PythonPartsExamples:
      - AllplanGeo.Move/Rotate/Transform return geometry directly (not tuples)
      - AllplanGeo.Rotate takes Axis3D(Point3D, Vector3D) + AllplanGeo.Angle
      - AllplanGeo.BRep3D.CreateCuboid(AxisPlacement3D, l, w, h) for positioned box
      - Polyhedron3D.CreateCuboid(Point3D min, Point3D max) for AABB form
    """
    import math

    start = _pt(spec.start)
    end = _pt(spec.end)

    dx = end.X - start.X
    dy = end.Y - start.Y
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1.0:
        raise AllplanApiError(f"Wall length {length:.1f}mm too small (min 1 mm)")

    angle = math.atan2(dy, dx)
    h = float(spec.height_mm)
    t = float(spec.thickness_mm)
    half_t = t / 2.0
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    # perpendicular unit vector (rotated 90° CCW from wall direction)
    px, py = -sin_a, cos_a

    _log.debug(
        "_wall: start=(%.0f,%.0f) end=(%.0f,%.0f) angle=%.4f len=%.1f t=%.1f h=%.1f",
        start.X, start.Y, end.X, end.Y, angle, length, t, h,
    )

    geo = None

    # 1. BRep3D.CreateCuboid with AxisPlacement3D — creates geometry at the
    # correct world position and orientation in one call (Allplan 2024+ API).
    # AxisPlacement3D(origin, x_axis, z_axis): x_axis = wall direction,
    # z_axis = up. Origin is shifted by -half_t in perpendicular so the wall
    # is centered on the start→end axis.
    try:
        origin = AllplanGeo.Point3D(
            start.X + sin_a * half_t,   # start - perp*half_t (perp = (-sin_a, cos_a))
            start.Y - cos_a * half_t,
            start.Z,
        )
        x_axis = AllplanGeo.Vector3D(cos_a, sin_a, 0.0)
        z_axis = AllplanGeo.Vector3D(0.0, 0.0, 1.0)
        placement = AllplanGeo.AxisPlacement3D(origin, x_axis, z_axis)
        geo = AllplanGeo.BRep3D.CreateCuboid(placement, length, t, h)
        _log.debug("_wall: attempt 1 (BRep3D+AxisPlacement3D) OK")
    except Exception as exc:
        _log.warning("_wall: attempt 1 (BRep3D+AxisPlacement3D) FAILED: %s", exc)

    # 2. Polyhedron3D.CreateCuboid(min, max) — 2-point AABB from the 8
    # world-space corner coordinates. Exact for axis-aligned walls; slightly
    # oversized for diagonal walls (bounding box approximation).
    if geo is None:
        try:
            corners_x = [
                start.X + px*half_t, start.X - px*half_t,
                end.X - px*half_t,   end.X + px*half_t,
            ]
            corners_y = [
                start.Y + py*half_t, start.Y - py*half_t,
                end.Y - py*half_t,   end.Y + py*half_t,
            ]
            pt_min = AllplanGeo.Point3D(min(corners_x), min(corners_y), start.Z)
            pt_max = AllplanGeo.Point3D(max(corners_x), max(corners_y), start.Z + h)
            geo = AllplanGeo.Polyhedron3D.CreateCuboid(pt_min, pt_max)
            _log.debug("_wall: attempt 2 (Polyhedron3D 2-pt AABB) OK")
        except Exception as exc:
            _log.warning("_wall: attempt 2 (Polyhedron3D 2-pt AABB) FAILED: %s", exc)

    # 3. Polyhedron3D at origin + AllplanGeo.Move + AllplanGeo.Rotate.
    # Move/Rotate return the transformed geometry directly (confirmed from examples).
    if geo is None:
        try:
            geo = AllplanGeo.Polyhedron3D.CreateCuboid(length, t, h)
            # Center the box on the wall axis (Y: 0→t becomes -half_t→+half_t)
            geo = AllplanGeo.Move(geo, AllplanGeo.Vector3D(0.0, -half_t, 0.0))
            # Rotate around Z to align with wall direction
            if abs(angle) > 1e-9:
                z_axis_obj = AllplanGeo.Axis3D(
                    AllplanGeo.Point3D(0.0, 0.0, 0.0),
                    AllplanGeo.Vector3D(0.0, 0.0, 1.0),
                )
                rot_angle = AllplanGeo.Angle()
                rot_angle.SetRad(angle)
                geo = AllplanGeo.Rotate(geo, z_axis_obj, rot_angle)
            # Translate to world start position
            geo = AllplanGeo.Move(geo, AllplanGeo.Vector3D(start.X, start.Y, start.Z))
            _log.debug("_wall: attempt 3 (Move/Rotate) OK")
        except Exception as exc:
            _log.warning("_wall: attempt 3 (Move/Rotate) FAILED: %s", exc)
            geo = AllplanGeo.Polyhedron3D.CreateCuboid(length, t, h)
            _log.error("_wall: ALL placement attempts failed — inserting at origin")

    common_props = _common_props(spec.layer)
    model_ele_cls = getattr(AllplanElements, "ModelElement3D", None)
    if model_ele_cls is None:
        raise AllplanApiError("ModelElement3D not available in AllplanElements")
    return model_ele_cls(common_props, geo)


# WallElement() constructor binds the object to NemAll_Python_ArchElements NOI
# virtual container at construction time, causing CNOI_VirtualArchContainer on
# CreateElements. Disabled until we find the API that passes the document at
# construction. Use ModelElement3D (plain geometry) instead.
_USE_ARCH_WALL = False


def build_wall_element(spec: WallSpec) -> Any:
    """Build a wall element from spec. Called from IFW callback context."""
    if _USE_ARCH_WALL and ArchElements is not None:
        start_pt = _pt(spec.start)
        end_pt = _pt(spec.end)
        axis_line = AllplanGeo.Line3D(start_pt, end_pt)
        common_props = _common_props(spec.layer)
        try:
            wall_props = _build_wall_properties(spec.height_mm, spec.thickness_mm)
            wall_elem = ArchElements.WallElement()
            wall_elem.SetGeometryObject(axis_line)
            wall_elem.SetProperties(wall_props)
            wall_elem.SetCommonProperties(common_props)
            return wall_elem
        except Exception as exc:
            _log.warning("build_wall_element: WallElement failed (%s); falling back", exc)
    return _wall_as_model_element(spec)


@command("create_wall")
def handle_create_wall(args: dict[str, Any]) -> dict[str, Any]:
    spec = WallSpec.model_validate(args)

    if _USING_FAKE:
        try:
            elem = AllplanElements.create_wall(
                start=_pt(spec.start),
                end=_pt(spec.end),
                height_mm=spec.height_mm,
                thickness_mm=spec.thickness_mm,
                layer=spec.layer,
            )
        except Exception as exc:
            raise AllplanApiError(f"create_wall (fake) failed: {exc}", exc) from exc
        _log.info("geometry.create_wall (fake) uuid=%s", elem.uuid)
        return ElementRef(uuid=elem.uuid, kind="wall").model_dump()

    if ArchElements is None:
        raise AllplanApiError(
            "NemAll_Python_ArchElements not importable — check Allplan installation."
        )

    # Queue only the spec — zero Allplan API calls here (QTimer context has no
    # valid document). McpBridgeInteractor._insert_pending builds and inserts
    # the element from on_preview_draw/process_mouse_msg (IFW callback context).
    uuid_str = str(_uuid_mod.uuid4())
    queue_spec("wall", spec)
    _log.info("geometry.create_wall queued spec uuid=%s", uuid_str)
    return ElementRef(uuid=uuid_str, kind="wall").model_dump()


# ---------------------------------------------------------------------------
# Slab / Column / Beam — real API not yet determined; fail clearly
# ---------------------------------------------------------------------------


@command("create_slab")
def handle_create_slab(args: dict[str, Any]) -> dict[str, Any]:
    spec = SlabSpec.model_validate(args)
    if _USING_FAKE:
        try:
            elem = AllplanElements.create_slab(
                outline=[_pt(p) for p in spec.outline],
                thickness_mm=spec.thickness_mm,
                layer=spec.layer,
            )
        except Exception as exc:
            raise AllplanApiError(f"create_slab (fake) failed: {exc}", exc) from exc
        _log.info("geometry.create_slab (fake) uuid=%s", elem.uuid)
        return ElementRef(uuid=elem.uuid, kind="slab").model_dump()
    raise AllplanApiError(
        "create_slab: real Allplan API not yet implemented. "
        "Use create_wall for now."
    )


@command("create_column")
def handle_create_column(args: dict[str, Any]) -> dict[str, Any]:
    spec = ColumnSpec.model_validate(args)
    if _USING_FAKE:
        try:
            elem = AllplanElements.create_column(
                base=_pt(spec.base),
                height_mm=spec.height_mm,
                width_mm=spec.width_mm,
                depth_mm=spec.depth_mm,
                layer=spec.layer,
            )
        except Exception as exc:
            raise AllplanApiError(f"create_column (fake) failed: {exc}", exc) from exc
        _log.info("geometry.create_column (fake) uuid=%s", elem.uuid)
        return ElementRef(uuid=elem.uuid, kind="column").model_dump()
    raise AllplanApiError(
        "create_column: real Allplan API not yet implemented."
    )


@command("create_beam")
def handle_create_beam(args: dict[str, Any]) -> dict[str, Any]:
    spec = BeamSpec.model_validate(args)
    if _USING_FAKE:
        try:
            elem = AllplanElements.create_beam(
                start=_pt(spec.start),
                end=_pt(spec.end),
                width_mm=spec.width_mm,
                height_mm=spec.height_mm,
                layer=spec.layer,
            )
        except Exception as exc:
            raise AllplanApiError(f"create_beam (fake) failed: {exc}", exc) from exc
        _log.info("geometry.create_beam (fake) uuid=%s", elem.uuid)
        return ElementRef(uuid=elem.uuid, kind="beam").model_dump()
    raise AllplanApiError(
        "create_beam: real Allplan API not yet implemented."
    )


# ---------------------------------------------------------------------------
# Element queries
# ---------------------------------------------------------------------------


@command("get_element")
def handle_get_element(args: dict[str, Any]) -> dict[str, Any]:
    ref = ElementRef.model_validate(args)
    try:
        elem = AllplanElements.get_element(ref.uuid)
    except Exception as exc:
        raise AllplanApiError(f"get_element failed: {exc}", exc) from exc
    if elem is None:
        raise KeyError(f"Element {ref.uuid!r} not found")
    return {"uuid": elem.uuid, "kind": elem.kind}


@command("delete_element")
def handle_delete_element(args: dict[str, Any]) -> dict[str, Any]:
    ref = ElementRef.model_validate(args)
    try:
        found = AllplanElements.delete_element(ref.uuid)
    except Exception as exc:
        raise AllplanApiError(f"delete_element failed: {exc}", exc) from exc
    if not found:
        raise KeyError(f"Element {ref.uuid!r} not found")
    return {"deleted": True, "uuid": ref.uuid}


@command("move_element")
def handle_move_element(args: dict[str, Any]) -> dict[str, Any]:
    ref = ElementRef.model_validate({"uuid": args["uuid"], "kind": args["kind"]})
    dx = float(args.get("dx", 0.0))
    dy = float(args.get("dy", 0.0))
    dz = float(args.get("dz", 0.0))
    try:
        ok = AllplanElements.move_element(ref.uuid, dx, dy, dz)
    except Exception as exc:
        raise AllplanApiError(f"move_element failed: {exc}", exc) from exc
    if not ok:
        raise KeyError(f"Element {ref.uuid!r} not found")
    return {"uuid": ref.uuid, "kind": ref.kind}
