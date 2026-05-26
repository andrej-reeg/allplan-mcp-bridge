"""Element reference models. Handlers return these instead of raw Allplan handles."""

from typing import Literal

from pydantic import BaseModel

ElementKind = Literal["wall", "slab", "column", "beam", "solid", "unknown"]


class ElementRef(BaseModel):
    """An opaque reference to an Allplan element.

    All create/mutate handlers return ElementRefs, never raw Allplan handles.
    The uuid is Allplan's internal element UUID; kind is the element type.
    """

    uuid: str
    kind: ElementKind
