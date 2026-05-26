"""Attribute handlers: get/set attributes on elements."""

import logging
from typing import Any

from allplan_mcp_server.models.attributes import AttributeSpec
from allplan_mcp_server.models.references import ElementRef

from ..dispatcher import command
from ..errors import AllplanApiError
from ._allplan import AllplanElements

_log = logging.getLogger(__name__)


@command("get_attributes")
def handle_get_attributes(args: dict[str, Any]) -> dict[str, Any]:
    ref = ElementRef.model_validate(args)
    try:
        elem = AllplanElements.get_element(ref.uuid)
    except Exception as exc:
        raise AllplanApiError(f"get_attributes failed: {exc}", exc) from exc
    if elem is None:
        raise KeyError(f"Element {ref.uuid!r} not found")
    attrs: dict[str, Any] = {
        k: v for k, v in elem._attrs.items()
        if isinstance(v, (str, int, float, bool))
    }
    return {"uuid": ref.uuid, "attributes": attrs}


@command("set_attributes")
def handle_set_attributes(args: dict[str, Any]) -> dict[str, Any]:
    ref = ElementRef.model_validate({"uuid": args["uuid"], "kind": args["kind"]})
    raw_attrs: list[dict[str, Any]] = args.get("attributes", [])
    specs = [AttributeSpec.model_validate(a) for a in raw_attrs]

    try:
        elem = AllplanElements.get_element(ref.uuid)
    except Exception as exc:
        raise AllplanApiError(f"set_attributes lookup failed: {exc}", exc) from exc
    if elem is None:
        raise KeyError(f"Element {ref.uuid!r} not found")

    try:
        for spec in specs:
            elem.set_attribute(spec.name, spec.value)
    except Exception as exc:
        raise AllplanApiError(f"set_attributes failed: {exc}", exc) from exc

    _log.info("attributes.set uuid=%s count=%d", ref.uuid, len(specs))
    return {"uuid": ref.uuid, "updated": len(specs)}
