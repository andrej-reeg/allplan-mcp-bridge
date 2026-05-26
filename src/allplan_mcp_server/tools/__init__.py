"""Tool registration. Import this package to register all tools on the mcp instance."""

from . import attributes, document, geometry, ifc, layers

__all__ = ["attributes", "document", "geometry", "ifc", "layers"]
