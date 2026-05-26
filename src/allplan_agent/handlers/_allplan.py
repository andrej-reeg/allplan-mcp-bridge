"""Single import shim for Allplan API modules.

All handlers import from here — never directly from NemAll_Python_*.
The try/except fallback is the ONLY place this import indirection lives.
"""

import logging

_log = logging.getLogger(__name__)

try:
    import NemAll_Python_AllplanSettings as AllplanSettings  # type: ignore[import-not-found]
    import NemAll_Python_BasisElements as AllplanElements  # type: ignore[import-not-found]
    import NemAll_Python_Geometry as AllplanGeo  # type: ignore[import-not-found]
    _USING_FAKE = False
except ImportError:
    from tests.fakes import fake_allplan_api as AllplanElements
    from tests.fakes import fake_allplan_api as AllplanGeo
    from tests.fakes import fake_allplan_api as AllplanSettings
    _USING_FAKE = True
    _log.warning(
        "Allplan modules not found — using fake API. "
        "This is expected outside Allplan's embedded Python."
    )

__all__ = ["AllplanElements", "AllplanGeo", "AllplanSettings", "_USING_FAKE"]
