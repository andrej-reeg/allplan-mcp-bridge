"""Persistent grid definition store backed by ~/.allplan-mcp/grids.json."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .models.grid import GridDefinition

_lock = threading.Lock()


def _grids_path() -> Path:
    return Path.home() / ".allplan-mcp" / "grids.json"


def load_grids() -> dict[str, GridDefinition]:
    p = _grids_path()
    if not p.exists():
        return {}
    with _lock:
        raw = json.loads(p.read_text(encoding="utf-8"))
    return {name: GridDefinition.model_validate(data) for name, data in raw.items()}


def save_grids(grids: dict[str, GridDefinition]) -> None:
    p = _grids_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        p.write_text(
            json.dumps(
                {name: g.model_dump(mode="json") for name, g in grids.items()},
                indent=2,
            ),
            encoding="utf-8",
        )


def list_grids() -> list[GridDefinition]:
    return list(load_grids().values())


def get_grid(name: str) -> GridDefinition:
    grids = load_grids()
    if name not in grids:
        raise KeyError(f"Grid {name!r} not defined. Call define_grid first.")
    return grids[name]


def put_grid(defn: GridDefinition) -> None:
    grids = load_grids()
    grids[defn.name] = defn
    save_grids(grids)


def delete_grid(name: str) -> None:
    grids = load_grids()
    if name not in grids:
        raise KeyError(f"Grid {name!r} not found.")
    del grids[name]
    save_grids(grids)
