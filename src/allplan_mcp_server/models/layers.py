"""Layer models for Allplan layer management."""

from pydantic import BaseModel, Field

_MAX_LAYER_NAME = 128


class LayerSpec(BaseModel):
    """Specification for creating or updating an Allplan layer.

    Side effects: creates or modifies a layer in the active Allplan document.
    Participates in undo.
    """

    name: str = Field(min_length=1, max_length=_MAX_LAYER_NAME)
    parent: str | None = Field(default=None, max_length=_MAX_LAYER_NAME)
    visible: bool = True
    locked: bool = False
