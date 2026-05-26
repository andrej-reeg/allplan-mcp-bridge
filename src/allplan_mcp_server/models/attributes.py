"""Attribute models for Allplan element attributes."""

from pydantic import BaseModel, Field

# Allplan attribute values are one of these scalar types.
AttributeValue = str | int | float | bool

# Allplan attribute names have a maximum practical length.
_MAX_NAME_LEN = 256


class AttributeSpec(BaseModel):
    """A single attribute name/value pair to get or set on an element."""

    name: str = Field(min_length=1, max_length=_MAX_NAME_LEN)
    value: AttributeValue


class AttributeDefinition(BaseModel):
    """Describes a known Allplan attribute (from the attribute definition list)."""

    id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=_MAX_NAME_LEN)
    data_type: str  # e.g. "string", "integer", "float", "boolean"
    description: str = ""
