"""Single import shim for Allplan API modules.

All handlers import from here — never directly from NemAll_Python_*.
The try/except fallback is the ONLY place this import indirection lives.

Import strategy:
  - NemAll_Python_BasisElements / Geometry / AllplanSettings: required by all
    handlers. Falls back to tests.fakes (dev/test only — not deployed to Allplan).
  - NemAll_Python_ArchElements / IFW_ElementAdapter: required only by real-API
    geometry handlers. Falls back to None so that a missing module never crashes
    the import chain inside Allplan's embedded Python (where tests.fakes is absent).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

_log = logging.getLogger(__name__)

# Stored by AllplanMcpBridge.McpBridgeInteractor on creation; read by geometry
# handlers that call CreateElements.
_coord_input: Any = None


def set_coord_input(ci: Any) -> None:
    global _coord_input
    _coord_input = ci


def get_coord_input() -> Any:
    return _coord_input


# Element specs queued by handlers (plain Python objects — NO Allplan API calls
# in the QTimer path). McpBridgeInteractor._insert_pending() runs from IFW
# callbacks (on_preview_draw / process_mouse_msg) where GetInputViewDocument()
# returns a valid context, builds the actual Allplan objects there, then calls
# BaseElements.CreateElements.
_pending_lock = threading.Lock()
_pending_specs: list[tuple[str, Any]] = []


def queue_spec(kind: str, spec: Any) -> None:
    with _pending_lock:
        _pending_specs.append((kind, spec))


def flush_pending_specs() -> list[tuple[str, Any]]:
    with _pending_lock:
        result = list(_pending_specs)
        _pending_specs.clear()
        return result


# --- Core modules (present in all Allplan 2024+; fall back to fakes in tests) ---
try:
    import NemAll_Python_AllplanSettings as AllplanSettings  # type: ignore[import-not-found]
    import NemAll_Python_BasisElements as AllplanElements  # type: ignore[import-not-found]
    import NemAll_Python_Geometry as AllplanGeo  # type: ignore[import-not-found]

    _USING_FAKE = False
except ImportError:
    # Only reached outside Allplan's embedded Python (e.g. unit tests on Linux/CI).
    from tests.fakes import fake_allplan_api as AllplanElements  # type: ignore[import-not-found]
    from tests.fakes import fake_allplan_api as AllplanGeo  # type: ignore[import-not-found]
    from tests.fakes import fake_allplan_api as AllplanSettings  # type: ignore[import-not-found]

    _USING_FAKE = True
    _log.warning(
        "Allplan modules not found — using fake API. "
        "This is expected outside Allplan's embedded Python."
    )

# --- Arch-element modules (Allplan 2026+; None if unavailable) ---
# Kept separate so a missing module never pollutes the core-module fallback above.
try:
    import NemAll_Python_BaseElements as BaseElements  # type: ignore[import-not-found]
except ImportError:
    BaseElements = None  # type: ignore[assignment]
    _log.warning("NemAll_Python_BaseElements not available — CommonProperties disabled")

try:
    import NemAll_Python_ArchElements as ArchElements  # type: ignore[import-not-found]
except ImportError:
    ArchElements = None  # type: ignore[assignment]
    _log.warning("NemAll_Python_ArchElements not available — real geometry API disabled")

try:
    import NemAll_Python_IFW_ElementAdapter as IFW  # type: ignore[import-not-found]
except ImportError:
    IFW = None  # type: ignore[assignment]
    _log.warning("NemAll_Python_IFW_ElementAdapter not available — real geometry API disabled")

__all__ = [
    "AllplanElements",
    "AllplanGeo",
    "AllplanSettings",
    "ArchElements",
    "BaseElements",
    "IFW",
    "_USING_FAKE",
    "flush_pending_specs",
    "get_coord_input",
    "queue_spec",
    "set_coord_input",
]
