"""Geometry handlers: wall, slab, column, beam, get/delete/move element."""

import logging
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
from ._allplan import AllplanElements

_log = logging.getLogger(__name__)


def _to_api_point(p: Any) -> Any:
    return AllplanElements.Point3D(x=p.x, y=p.y, z=p.z)


def _elem_to_ref(elem: Any, kind: str) -> dict[str, Any]:
    return ElementRef(uuid=elem.uuid, kind=kind).model_dump()  # type: ignore[arg-type]


@command("create_wall")
def handle_create_wall(args: dict[str, Any]) -> dict[str, Any]:
    spec = WallSpec.model_validate(args)
    try:
        elem = AllplanElements.create_wall(
            start=_to_api_point(spec.start),
            end=_to_api_point(spec.end),
            height_mm=spec.height_mm,
            thickness_mm=spec.thickness_mm,
            layer=spec.layer,
        )
    except Exception as exc:
        raise AllplanApiError(f"create_wall failed: {exc}", exc) from exc
    _log.info("geometry.create_wall uuid=%s", elem.uuid)
    return _elem_to_ref(elem, "wall")


@command("create_slab")
def handle_create_slab(args: dict[str, Any]) -> dict[str, Any]:
    spec = SlabSpec.model_validate(args)
    try:
        elem = AllplanElements.create_slab(
            outline=[_to_api_point(p) for p in spec.outline],
            thickness_mm=spec.thickness_mm,
            layer=spec.layer,
        )
    except Exception as exc:
        raise AllplanApiError(f"create_slab failed: {exc}", exc) from exc
    _log.info("geometry.create_slab uuid=%s", elem.uuid)
    return _elem_to_ref(elem, "slab")


@command("create_column")
def handle_create_column(args: dict[str, Any]) -> dict[str, Any]:
    spec = ColumnSpec.model_validate(args)
    try:
        elem = AllplanElements.create_column(
            base=_to_api_point(spec.base),
            height_mm=spec.height_mm,
            width_mm=spec.width_mm,
            depth_mm=spec.depth_mm,
            layer=spec.layer,
        )
    except Exception as exc:
        raise AllplanApiError(f"create_column failed: {exc}", exc) from exc
    _log.info("geometry.create_column uuid=%s", elem.uuid)
    return _elem_to_ref(elem, "column")


@command("create_beam")
def handle_create_beam(args: dict[str, Any]) -> dict[str, Any]:
    spec = BeamSpec.model_validate(args)
    try:
        elem = AllplanElements.create_beam(
            start=_to_api_point(spec.start),
            end=_to_api_point(spec.end),
            width_mm=spec.width_mm,
            height_mm=spec.height_mm,
            layer=spec.layer,
        )
    except Exception as exc:
        raise AllplanApiError(f"create_beam failed: {exc}", exc) from exc
    _log.info("geometry.create_beam uuid=%s", elem.uuid)
    return _elem_to_ref(elem, "beam")


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
