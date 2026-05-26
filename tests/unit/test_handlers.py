"""Handler tests using fake Allplan API. No real Allplan required."""

from pathlib import Path

import pytest

from tests.fakes.fake_allplan_api import reset_all


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_all()
    # Re-import so handlers pick up fresh state
    import importlib

    import tests.fakes.fake_allplan_api as _fa
    importlib.reload(_fa)
    reset_all()


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def test_create_wall_returns_element_ref() -> None:
    from allplan_agent.handlers.geometry import handle_create_wall
    result = handle_create_wall({
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 5000, "y": 0, "z": 0},
        "height_mm": 2800,
        "thickness_mm": 200,
    })
    assert result["kind"] == "wall"
    assert isinstance(result["uuid"], str)


def test_create_wall_invalid_args_raises() -> None:
    from pydantic import ValidationError

    from allplan_agent.handlers.geometry import handle_create_wall
    with pytest.raises(ValidationError):
        handle_create_wall({"start": {"x": 0, "y": 0, "z": 0}})


def test_create_slab_returns_element_ref() -> None:
    from allplan_agent.handlers.geometry import handle_create_slab
    result = handle_create_slab({
        "outline": [
            {"x": 0, "y": 0, "z": 0},
            {"x": 6000, "y": 0, "z": 0},
            {"x": 6000, "y": 4000, "z": 0},
        ],
        "thickness_mm": 200,
    })
    assert result["kind"] == "slab"


def test_create_column_returns_element_ref() -> None:
    from allplan_agent.handlers.geometry import handle_create_column
    result = handle_create_column({
        "base": {"x": 0, "y": 0, "z": 0},
        "height_mm": 3000,
        "width_mm": 400,
        "depth_mm": 400,
    })
    assert result["kind"] == "column"


def test_create_beam_returns_element_ref() -> None:
    from allplan_agent.handlers.geometry import handle_create_beam
    result = handle_create_beam({
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 5000, "y": 0, "z": 0},
        "width_mm": 300,
        "height_mm": 500,
    })
    assert result["kind"] == "beam"


def test_get_element_found() -> None:
    from allplan_agent.handlers.geometry import handle_create_wall, handle_get_element
    ref = handle_create_wall({
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 5000, "y": 0, "z": 0},
        "height_mm": 2800,
        "thickness_mm": 200,
    })
    result = handle_get_element({"uuid": ref["uuid"], "kind": "wall"})
    assert result["uuid"] == ref["uuid"]


def test_get_element_not_found_raises() -> None:
    from allplan_agent.handlers.geometry import handle_get_element
    with pytest.raises(KeyError):
        handle_get_element({"uuid": "nonexistent", "kind": "wall"})


def test_delete_element() -> None:
    from allplan_agent.handlers.geometry import handle_create_wall, handle_delete_element
    ref = handle_create_wall({
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 5000, "y": 0, "z": 0},
        "height_mm": 2800,
        "thickness_mm": 200,
    })
    result = handle_delete_element({"uuid": ref["uuid"], "kind": "wall"})
    assert result["deleted"] is True


def test_delete_element_not_found_raises() -> None:
    from allplan_agent.handlers.geometry import handle_delete_element
    with pytest.raises(KeyError):
        handle_delete_element({"uuid": "ghost", "kind": "wall"})


def test_move_element() -> None:
    from allplan_agent.handlers.geometry import handle_create_wall, handle_move_element
    ref = handle_create_wall({
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 5000, "y": 0, "z": 0},
        "height_mm": 2800,
        "thickness_mm": 200,
    })
    result = handle_move_element({"uuid": ref["uuid"], "kind": "wall", "dx": 100, "dy": 0, "dz": 0})
    assert result["uuid"] == ref["uuid"]


def test_move_element_not_found_raises() -> None:
    from allplan_agent.handlers.geometry import handle_move_element
    with pytest.raises(KeyError):
        handle_move_element({"uuid": "ghost", "kind": "wall", "dx": 0, "dy": 0, "dz": 0})


# ---------------------------------------------------------------------------
# Attributes
# ---------------------------------------------------------------------------

def test_set_and_get_attributes() -> None:
    from allplan_agent.handlers.attributes import handle_get_attributes, handle_set_attributes
    from allplan_agent.handlers.geometry import handle_create_wall
    ref = handle_create_wall({
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 5000, "y": 0, "z": 0},
        "height_mm": 2800,
        "thickness_mm": 200,
    })
    handle_set_attributes({
        "uuid": ref["uuid"],
        "kind": "wall",
        "attributes": [{"name": "FireRating", "value": "F30"}],
    })
    result = handle_get_attributes({"uuid": ref["uuid"], "kind": "wall"})
    assert result["attributes"]["FireRating"] == "F30"


def test_get_attributes_not_found() -> None:
    from allplan_agent.handlers.attributes import handle_get_attributes
    with pytest.raises(KeyError):
        handle_get_attributes({"uuid": "ghost", "kind": "wall"})


def test_set_attributes_not_found() -> None:
    from allplan_agent.handlers.attributes import handle_set_attributes
    with pytest.raises(KeyError):
        handle_set_attributes({
            "uuid": "ghost",
            "kind": "wall",
            "attributes": [{"name": "x", "value": 1}],
        })


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------

def test_create_and_list_layers() -> None:
    from allplan_agent.handlers.layers import handle_create_layer, handle_list_layers
    handle_create_layer({"name": "EXTERIOR"})
    result = handle_list_layers({})
    names = [layer["name"] for layer in result["layers"]]
    assert "EXTERIOR" in names


def test_set_layer_visibility() -> None:
    from allplan_agent.handlers.layers import handle_create_layer, handle_set_layer_visibility
    handle_create_layer({"name": "STRUCTURE"})
    result = handle_set_layer_visibility({"name": "STRUCTURE", "visible": False})
    assert result["visible"] is False


def test_set_layer_visibility_not_found() -> None:
    from allplan_agent.handlers.layers import handle_set_layer_visibility
    with pytest.raises(KeyError):
        handle_set_layer_visibility({"name": "GHOST", "visible": True})


def test_assign_layer() -> None:
    from allplan_agent.handlers.geometry import handle_create_wall
    from allplan_agent.handlers.layers import handle_assign_layer, handle_create_layer
    handle_create_layer({"name": "EXTERIOR"})
    ref = handle_create_wall({
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 5000, "y": 0, "z": 0},
        "height_mm": 2800,
        "thickness_mm": 200,
    })
    result = handle_assign_layer({"uuid": ref["uuid"], "kind": "wall", "layer": "EXTERIOR"})
    assert result["layer"] == "EXTERIOR"


def test_assign_layer_missing_layer_raises() -> None:
    from allplan_agent.handlers.geometry import handle_create_wall
    from allplan_agent.handlers.layers import handle_assign_layer
    ref = handle_create_wall({
        "start": {"x": 0, "y": 0, "z": 0},
        "end": {"x": 5000, "y": 0, "z": 0},
        "height_mm": 2800,
        "thickness_mm": 200,
    })
    with pytest.raises(KeyError):
        handle_assign_layer({"uuid": ref["uuid"], "kind": "wall", "layer": "GHOST"})


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------

def test_get_active_document_info() -> None:
    from allplan_agent.handlers.document import handle_get_active_document_info
    info = handle_get_active_document_info({})
    assert "name" in info
    assert "path" in info


def test_save_document() -> None:
    from allplan_agent.handlers.document import handle_save_document
    result = handle_save_document({})
    assert result["saved"] is True


def test_undo_redo() -> None:
    from allplan_agent.handlers.document import handle_redo, handle_undo
    assert handle_undo({})["ok"] is True
    assert handle_redo({})["ok"] is True


# ---------------------------------------------------------------------------
# IFC
# ---------------------------------------------------------------------------

def test_export_ifc(tmp_path: Path) -> None:
    from allplan_agent.handlers.ifc import handle_export_ifc, set_workspace_root
    set_workspace_root(tmp_path)
    result = handle_export_ifc({
        "path": str(tmp_path / "model.ifc"),
        "schema_version": "IFC4",
    })
    assert result["exported"] is True


def test_export_ifc_path_outside_workspace(tmp_path: Path) -> None:
    from allplan_agent.errors import AllplanApiError
    from allplan_agent.handlers.ifc import handle_export_ifc, set_workspace_root
    set_workspace_root(tmp_path)
    with pytest.raises(AllplanApiError, match="outside the allowed workspace"):
        handle_export_ifc({"path": "/etc/evil.ifc", "schema_version": "IFC4"})


def test_import_ifc(tmp_path: Path) -> None:
    from allplan_agent.handlers.ifc import handle_import_ifc, set_workspace_root
    set_workspace_root(tmp_path)
    ifc_file = tmp_path / "input.ifc"
    ifc_file.write_text("")
    result = handle_import_ifc({"path": str(ifc_file)})
    assert result["imported"] >= 1
    assert result["elements"][0]["kind"] == "unknown"


def test_export_ifc_invalid_schema() -> None:
    from pydantic import ValidationError

    from allplan_agent.handlers.ifc import handle_export_ifc
    with pytest.raises(ValidationError):
        handle_export_ifc({"path": "/workspace/model.ifc", "schema_version": "IFC9"})
