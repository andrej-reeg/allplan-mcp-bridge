"""Tests for allplan_mcp_server/models/. Target: 100% branch coverage on validators."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from allplan_mcp_server.models.attributes import AttributeDefinition, AttributeSpec
from allplan_mcp_server.models.geometry import (
    _MAX_EXTENT_MM,
    BeamSpec,
    ColumnSpec,
    GenericSolidSpec,
    Point3D,
    SlabSpec,
    Vector3D,
    WallSpec,
)
from allplan_mcp_server.models.ifc import IfcExportSpec, IfcImportSpec
from allplan_mcp_server.models.layers import LayerSpec
from allplan_mcp_server.models.references import ElementRef

# ---------------------------------------------------------------------------
# Point3D / Vector3D
# ---------------------------------------------------------------------------


def test_point3d_valid() -> None:
    p = Point3D(x=0.0, y=1000.0, z=-500.0)
    assert p.x == 0.0


def test_point3d_nan_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        Point3D(x=float("nan"), y=0.0, z=0.0)


def test_point3d_inf_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        Point3D(x=float("inf"), y=0.0, z=0.0)


def test_point3d_neg_inf_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        Point3D(x=0.0, y=float("-inf"), z=0.0)


def test_point3d_z_nan_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        Point3D(x=0.0, y=0.0, z=float("nan"))


def test_vector3d_valid() -> None:
    v = Vector3D(x=1.0, y=0.0, z=0.0)
    assert v.x == 1.0


def test_vector3d_nan_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        Vector3D(x=float("nan"), y=0.0, z=0.0)


def test_point3d_distance_to() -> None:
    a = Point3D(x=0.0, y=0.0, z=0.0)
    b = Point3D(x=3000.0, y=4000.0, z=0.0)
    assert abs(a.distance_to(b) - 5000.0) < 0.01


# ---------------------------------------------------------------------------
# WallSpec
# ---------------------------------------------------------------------------

_P0 = Point3D(x=0.0, y=0.0, z=0.0)
_P1 = Point3D(x=5000.0, y=0.0, z=0.0)


def test_wall_valid() -> None:
    w = WallSpec(start=_P0, end=_P1, height_mm=2800.0, thickness_mm=200.0)
    assert w.height_mm == 2800.0


def test_wall_negative_height_rejected() -> None:
    with pytest.raises(ValidationError):
        WallSpec(start=_P0, end=_P1, height_mm=-1.0, thickness_mm=200.0)


def test_wall_zero_height_rejected() -> None:
    with pytest.raises(ValidationError):
        WallSpec(start=_P0, end=_P1, height_mm=0.0, thickness_mm=200.0)


def test_wall_negative_thickness_rejected() -> None:
    with pytest.raises(ValidationError):
        WallSpec(start=_P0, end=_P1, height_mm=2800.0, thickness_mm=-1.0)


def test_wall_zero_thickness_rejected() -> None:
    with pytest.raises(ValidationError):
        WallSpec(start=_P0, end=_P1, height_mm=2800.0, thickness_mm=0.0)


def test_wall_degenerate_start_eq_end() -> None:
    with pytest.raises(ValidationError, match="degenerate"):
        WallSpec(start=_P0, end=_P0, height_mm=2800.0, thickness_mm=200.0)


def test_wall_length_exceeds_max() -> None:
    far = Point3D(x=_MAX_EXTENT_MM + 1000.0, y=0.0, z=0.0)
    with pytest.raises(ValidationError, match="exceeds maximum"):
        WallSpec(start=_P0, end=far, height_mm=2800.0, thickness_mm=200.0)


def test_wall_height_exceeds_max() -> None:
    with pytest.raises(ValidationError):
        WallSpec(start=_P0, end=_P1, height_mm=_MAX_EXTENT_MM + 1, thickness_mm=200.0)


def test_wall_layer_optional() -> None:
    w = WallSpec(start=_P0, end=_P1, height_mm=2800.0, thickness_mm=200.0, layer="EXTERIOR")
    assert w.layer == "EXTERIOR"


def test_wall_json_roundtrip() -> None:
    w = WallSpec(start=_P0, end=_P1, height_mm=2800.0, thickness_mm=200.0)
    w2 = WallSpec.model_validate_json(w.model_dump_json())
    assert w2 == w


# ---------------------------------------------------------------------------
# SlabSpec
# ---------------------------------------------------------------------------

_SLAB_OUTLINE = [
    Point3D(x=0.0, y=0.0, z=0.0),
    Point3D(x=6000.0, y=0.0, z=0.0),
    Point3D(x=6000.0, y=4000.0, z=0.0),
    Point3D(x=0.0, y=4000.0, z=0.0),
]


def test_slab_valid() -> None:
    s = SlabSpec(outline=_SLAB_OUTLINE, thickness_mm=200.0)
    assert s.thickness_mm == 200.0


def test_slab_too_few_points() -> None:
    with pytest.raises(ValidationError):
        SlabSpec(outline=_SLAB_OUTLINE[:2], thickness_mm=200.0)


def test_slab_zero_thickness_rejected() -> None:
    with pytest.raises(ValidationError):
        SlabSpec(outline=_SLAB_OUTLINE, thickness_mm=0.0)


# ---------------------------------------------------------------------------
# ColumnSpec
# ---------------------------------------------------------------------------


def test_column_valid() -> None:
    c = ColumnSpec(base=_P0, height_mm=3000.0, width_mm=400.0, depth_mm=400.0)
    assert c.height_mm == 3000.0


def test_column_zero_height_rejected() -> None:
    with pytest.raises(ValidationError):
        ColumnSpec(base=_P0, height_mm=0.0, width_mm=400.0, depth_mm=400.0)


def test_column_zero_width_rejected() -> None:
    with pytest.raises(ValidationError):
        ColumnSpec(base=_P0, height_mm=3000.0, width_mm=0.0, depth_mm=400.0)


def test_column_zero_depth_rejected() -> None:
    with pytest.raises(ValidationError):
        ColumnSpec(base=_P0, height_mm=3000.0, width_mm=400.0, depth_mm=0.0)


# ---------------------------------------------------------------------------
# BeamSpec
# ---------------------------------------------------------------------------


def test_beam_valid() -> None:
    b = BeamSpec(start=_P0, end=_P1, width_mm=300.0, height_mm=500.0)
    assert b.width_mm == 300.0


def test_beam_degenerate_rejected() -> None:
    with pytest.raises(ValidationError, match="degenerate"):
        BeamSpec(start=_P0, end=_P0, width_mm=300.0, height_mm=500.0)


def test_beam_zero_width_rejected() -> None:
    with pytest.raises(ValidationError):
        BeamSpec(start=_P0, end=_P1, width_mm=0.0, height_mm=500.0)


# ---------------------------------------------------------------------------
# GenericSolidSpec
# ---------------------------------------------------------------------------

_TETRA_VERTS = [
    Point3D(x=0.0, y=0.0, z=0.0),
    Point3D(x=1000.0, y=0.0, z=0.0),
    Point3D(x=500.0, y=1000.0, z=0.0),
    Point3D(x=500.0, y=333.0, z=800.0),
]
_TETRA_FACES = [[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]]


def test_solid_valid() -> None:
    s = GenericSolidSpec(vertices=_TETRA_VERTS, faces=_TETRA_FACES)
    assert len(s.vertices) == 4


def test_solid_too_few_vertices() -> None:
    with pytest.raises(ValidationError):
        GenericSolidSpec(
            vertices=_TETRA_VERTS[:3],
            faces=_TETRA_FACES,
        )


def test_solid_too_few_faces() -> None:
    with pytest.raises(ValidationError):
        GenericSolidSpec(
            vertices=_TETRA_VERTS,
            faces=_TETRA_FACES[:3],
        )


def test_solid_face_index_out_of_range() -> None:
    bad_faces = [[0, 1, 99], [0, 1, 3], [0, 2, 3], [1, 2, 3]]
    with pytest.raises(ValidationError, match="out of range"):
        GenericSolidSpec(vertices=_TETRA_VERTS, faces=bad_faces)


def test_solid_face_too_few_vertices() -> None:
    bad_faces = [[0, 1], [0, 1, 3], [0, 2, 3], [1, 2, 3]]
    with pytest.raises(ValidationError, match="at least 3"):
        GenericSolidSpec(vertices=_TETRA_VERTS, faces=bad_faces)


# ---------------------------------------------------------------------------
# ElementRef
# ---------------------------------------------------------------------------


def test_element_ref_valid() -> None:
    r = ElementRef(uuid="abc-123", kind="wall")
    assert r.kind == "wall"


def test_element_ref_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        ElementRef(uuid="abc-123", kind="window")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AttributeSpec / AttributeDefinition
# ---------------------------------------------------------------------------


def test_attribute_spec_string() -> None:
    a = AttributeSpec(name="FireRating", value="F30")
    assert a.value == "F30"


def test_attribute_spec_int() -> None:
    a = AttributeSpec(name="Floor", value=3)
    assert a.value == 3


def test_attribute_spec_float() -> None:
    a = AttributeSpec(name="Area", value=45.5)
    assert a.value == 45.5


def test_attribute_spec_bool() -> None:
    a = AttributeSpec(name="Load_Bearing", value=True)
    assert a.value is True


def test_attribute_spec_empty_name_rejected() -> None:
    with pytest.raises(ValidationError):
        AttributeSpec(name="", value="x")


def test_attribute_definition_valid() -> None:
    d = AttributeDefinition(id=1, name="FireRating", data_type="string")
    assert d.id == 1


def test_attribute_definition_zero_id_rejected() -> None:
    with pytest.raises(ValidationError):
        AttributeDefinition(id=0, name="x", data_type="string")


# ---------------------------------------------------------------------------
# LayerSpec
# ---------------------------------------------------------------------------


def test_layer_spec_valid() -> None:
    layer = LayerSpec(name="EXTERIOR", visible=True, locked=False)
    assert layer.name == "EXTERIOR"


def test_layer_spec_empty_name_rejected() -> None:
    with pytest.raises(ValidationError):
        LayerSpec(name="")


def test_layer_spec_with_parent() -> None:
    layer = LayerSpec(name="WALL", parent="STRUCTURE")
    assert layer.parent == "STRUCTURE"


# ---------------------------------------------------------------------------
# IfcExportSpec / IfcImportSpec
# ---------------------------------------------------------------------------


def test_ifc_export_valid() -> None:
    spec = IfcExportSpec(path=Path("/workspace/model.ifc"), schema_version="IFC4")
    assert spec.schema_version == "IFC4"


def test_ifc_export_ifc2x3() -> None:
    spec = IfcExportSpec(path=Path("/workspace/model.ifc"), schema_version="IFC2X3")
    assert spec.schema_version == "IFC2X3"


def test_ifc_export_invalid_schema() -> None:
    with pytest.raises(ValidationError):
        IfcExportSpec(
            path=Path("/workspace/model.ifc"),
            schema_version="IFC5",  # type: ignore[arg-type]
        )


def test_ifc_export_relative_path_rejected() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        IfcExportSpec(path=Path("relative/model.ifc"))


def test_ifc_export_wrong_extension_rejected() -> None:
    with pytest.raises(ValidationError, match=".ifc"):
        IfcExportSpec(path=Path("/workspace/model.xml"))


def test_ifc_export_with_elements() -> None:
    refs = [ElementRef(uuid="x", kind="wall")]
    spec = IfcExportSpec(path=Path("/workspace/model.ifc"), elements=refs)
    assert spec.elements is not None
    assert len(spec.elements) == 1


def test_ifc_import_valid() -> None:
    spec = IfcImportSpec(path=Path("/workspace/model.ifc"))
    assert spec.path.suffix == ".ifc"


def test_ifc_import_relative_path_rejected() -> None:
    with pytest.raises(ValidationError, match="absolute"):
        IfcImportSpec(path=Path("model.ifc"))


def test_ifc_import_wrong_extension_rejected() -> None:
    with pytest.raises(ValidationError, match=".ifc"):
        IfcImportSpec(path=Path("/workspace/model.step"))
