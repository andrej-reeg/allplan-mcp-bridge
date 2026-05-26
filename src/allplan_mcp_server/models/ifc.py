"""IFC import/export models."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .references import ElementRef

IfcSchema = Literal["IFC2X3", "IFC4"]

# Hard limits for IFC file sizes (bytes).
IFC_WARN_BYTES = 100 * 1024 * 1024   # 100 MiB
IFC_HARD_LIMIT_BYTES = 1024 * 1024 * 1024  # 1 GiB


class IfcExportSpec(BaseModel):
    """Specification for exporting elements to an IFC file.

    Units: path is an absolute path inside the allowed workspace root.
    Side effects: writes an IFC file to disk.
    Participates in undo (the export itself is not undoable, but any
    pre-export transformations are).
    """

    path: Path
    schema_version: IfcSchema = "IFC4"
    elements: list[ElementRef] | None = Field(
        default=None,
        description="Elements to export. None means export the full model.",
    )

    @field_validator("path")
    @classmethod
    def _must_be_absolute(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"IFC export path must be absolute, got {v!r}")
        return v

    @field_validator("path")
    @classmethod
    def _must_have_ifc_extension(cls, v: Path) -> Path:
        if v.suffix.lower() != ".ifc":
            raise ValueError(f"IFC export path must end in .ifc, got {v.suffix!r}")
        return v


class IfcImportSpec(BaseModel):
    """Specification for importing an IFC file into the active document.

    Units: path is an absolute path inside the allowed workspace root.
    Side effects: creates elements in the active Allplan document.
    Participates in undo (entire import wrapped in one bracket).
    """

    path: Path

    @field_validator("path")
    @classmethod
    def _must_be_absolute(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError(f"IFC import path must be absolute, got {v!r}")
        return v

    @field_validator("path")
    @classmethod
    def _must_have_ifc_extension(cls, v: Path) -> Path:
        if v.suffix.lower() != ".ifc":
            raise ValueError(f"IFC import path must end in .ifc, got {v.suffix!r}")
        return v
