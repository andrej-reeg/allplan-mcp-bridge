"""Unit tests for grid store, models, and element cache."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from allplan_mcp_server.element_cache import lookup, offset_spec, store
from allplan_mcp_server.grid_store import (
    delete_grid,
    get_grid,
    list_grids,
    put_grid,
)
from allplan_mcp_server.models.grid import GridDefinition, GridLine

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# GridDefinition helpers
# ---------------------------------------------------------------------------


def _make_grid(name: str = "Test") -> GridDefinition:
    return GridDefinition(
        name=name,
        x_lines=[
            GridLine(name="28", coordinate_mm=28000.0),
            GridLine(name="29", coordinate_mm=29000.0),
            GridLine(name="30", coordinate_mm=30000.0),
        ],
        y_lines=[
            GridLine(name="A", coordinate_mm=4500.0),
            GridLine(name="B", coordinate_mm=9000.0),
        ],
        z_base_mm=0.0,
    )


# ---------------------------------------------------------------------------
# GridDefinition — model tests
# ---------------------------------------------------------------------------


def test_x_line_lookup() -> None:
    g = _make_grid()
    assert g.x_line("28").coordinate_mm == 28000.0


def test_y_line_lookup() -> None:
    g = _make_grid()
    assert g.y_line("A").coordinate_mm == 4500.0


def test_x_line_missing_raises() -> None:
    g = _make_grid()
    with pytest.raises(KeyError, match="99"):
        g.x_line("99")


def test_y_line_missing_raises() -> None:
    g = _make_grid()
    with pytest.raises(KeyError, match="Z"):
        g.y_line("Z")


# ---------------------------------------------------------------------------
# Grid store — persistence
# ---------------------------------------------------------------------------


def test_put_and_get_grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "allplan_mcp_server.grid_store._grids_path",
        lambda: tmp_path / "grids.json",
    )
    defn = _make_grid("Main")
    put_grid(defn)
    loaded = get_grid("Main")
    assert loaded.name == "Main"
    assert len(loaded.x_lines) == 3
    assert loaded.x_lines[0].coordinate_mm == 28000.0


def test_list_grids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "allplan_mcp_server.grid_store._grids_path",
        lambda: tmp_path / "grids.json",
    )
    put_grid(_make_grid("G1"))
    put_grid(_make_grid("G2"))
    grids = list_grids()
    assert {g.name for g in grids} == {"G1", "G2"}


def test_delete_grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "allplan_mcp_server.grid_store._grids_path",
        lambda: tmp_path / "grids.json",
    )
    put_grid(_make_grid("ToDelete"))
    delete_grid("ToDelete")
    with pytest.raises(KeyError):
        get_grid("ToDelete")


def test_get_missing_grid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "allplan_mcp_server.grid_store._grids_path",
        lambda: tmp_path / "grids.json",
    )
    with pytest.raises(KeyError, match="NoSuchGrid"):
        get_grid("NoSuchGrid")


def test_grid_json_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "grids.json"
    monkeypatch.setattr("allplan_mcp_server.grid_store._grids_path", lambda: p)
    put_grid(_make_grid("RT"))
    raw = json.loads(p.read_text())
    assert "RT" in raw
    assert raw["RT"]["x_lines"][1]["name"] == "29"


# ---------------------------------------------------------------------------
# Element cache
# ---------------------------------------------------------------------------


def test_store_and_lookup() -> None:
    store("uuid-1", "column", {"base": {"x": 100, "y": 200, "z": 0}})
    result = lookup("uuid-1")
    assert result is not None
    assert result["kind"] == "column"
    assert result["spec"]["base"]["x"] == 100


def test_lookup_missing_returns_none() -> None:
    assert lookup("no-such-uuid") is None


def test_store_deep_copies_spec() -> None:
    spec = {"base": {"x": 0, "y": 0, "z": 0}}
    store("uuid-2", "column", spec)
    spec["base"]["x"] = 9999  # mutate original
    cached = lookup("uuid-2")
    assert cached is not None
    assert cached["spec"]["base"]["x"] == 0  # cache unaffected


# ---------------------------------------------------------------------------
# offset_spec
# ---------------------------------------------------------------------------


def test_offset_column() -> None:
    spec = {"base": {"x": 1000.0, "y": 2000.0, "z": 0.0}, "height_mm": 3000}
    shifted = offset_spec("column", spec, dx=5000.0, dy=0.0, dz=0.0)
    assert shifted["base"]["x"] == 6000.0
    assert shifted["base"]["y"] == 2000.0
    assert shifted["base"]["z"] == 0.0


def test_offset_wall() -> None:
    spec = {
        "start": {"x": 0.0, "y": 0.0, "z": 0.0},
        "end": {"x": 5000.0, "y": 0.0, "z": 0.0},
        "height_mm": 3000,
        "thickness_mm": 300,
    }
    shifted = offset_spec("wall", spec, dx=1000.0, dy=500.0, dz=0.0)
    assert shifted["start"]["x"] == 1000.0
    assert shifted["start"]["y"] == 500.0
    assert shifted["end"]["x"] == 6000.0


def test_offset_slab() -> None:
    spec = {
        "outline": [
            {"x": 0.0, "y": 0.0, "z": 0.0},
            {"x": 5000.0, "y": 0.0, "z": 0.0},
            {"x": 5000.0, "y": 4000.0, "z": 0.0},
        ],
        "thickness_mm": 200,
    }
    shifted = offset_spec("slab", spec, dx=2000.0, dy=0.0, dz=0.0)
    assert shifted["outline"][0]["x"] == 2000.0
    assert shifted["outline"][1]["x"] == 7000.0


def test_offset_does_not_mutate_original() -> None:
    spec = {"base": {"x": 0.0, "y": 0.0, "z": 0.0}, "height_mm": 3000}
    offset_spec("column", spec, dx=999.0, dy=0.0, dz=0.0)
    assert spec["base"]["x"] == 0.0
