"""Layer handlers: list, create, set visibility, assign to element."""

import logging
from typing import Any

from allplan_mcp_server.models.layers import LayerSpec
from allplan_mcp_server.models.references import ElementRef

from ..dispatcher import command
from ..errors import AllplanApiError
from ._allplan import AllplanElements, AllplanSettings

_log = logging.getLogger(__name__)


@command("list_layers")
def handle_list_layers(args: dict[str, Any]) -> dict[str, Any]:
    try:
        layers = AllplanSettings.list_layers()
    except Exception as exc:
        raise AllplanApiError(f"list_layers failed: {exc}", exc) from exc
    return {"layers": layers}


@command("create_layer")
def handle_create_layer(args: dict[str, Any]) -> dict[str, Any]:
    spec = LayerSpec.model_validate(args)
    try:
        layer = AllplanSettings.create_layer(
            name=spec.name,
            parent=spec.parent,
            visible=spec.visible,
            locked=spec.locked,
        )
    except Exception as exc:
        raise AllplanApiError(f"create_layer failed: {exc}", exc) from exc
    _log.info("layers.create name=%s", spec.name)
    return {"layer": layer}


@command("set_layer_visibility")
def handle_set_layer_visibility(args: dict[str, Any]) -> dict[str, Any]:
    name: str = args["name"]
    visible: bool = bool(args["visible"])
    try:
        layer = AllplanSettings.get_layer(name)
    except Exception as exc:
        raise AllplanApiError(f"set_layer_visibility failed: {exc}", exc) from exc
    if layer is None:
        raise KeyError(f"Layer {name!r} not found")
    layer["visible"] = visible
    return {"name": name, "visible": visible}


@command("assign_layer")
def handle_assign_layer(args: dict[str, Any]) -> dict[str, Any]:
    ref = ElementRef.model_validate({"uuid": args["uuid"], "kind": args["kind"]})
    layer_name: str = args["layer"]
    try:
        layer = AllplanSettings.get_layer(layer_name)
        if layer is None:
            raise KeyError(f"Layer {layer_name!r} not found")
        elem = AllplanElements.get_element(ref.uuid)
        if elem is None:
            raise KeyError(f"Element {ref.uuid!r} not found")
        elem.set_attribute("layer", layer_name)
    except (KeyError, AllplanApiError):
        raise
    except Exception as exc:
        raise AllplanApiError(f"assign_layer failed: {exc}", exc) from exc
    _log.info("layers.assign uuid=%s layer=%s", ref.uuid, layer_name)
    return {"uuid": ref.uuid, "layer": layer_name}
