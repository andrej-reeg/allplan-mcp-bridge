"""Agent-side safety controls: undo bracket and path allowlist."""

import contextlib
import logging
from collections.abc import Generator
from pathlib import Path

_log = logging.getLogger(__name__)


class PathNotAllowedError(ValueError):
    """Raised when a path falls outside the workspace root."""


def validate_path(path: Path, workspace_root: Path) -> Path:
    """Resolve path and verify it is inside workspace_root.

    Raises PathNotAllowedError for:
    - relative paths
    - paths resolving outside workspace_root (including .. traversal)
    - symlinks pointing outside workspace_root
    """
    if not path.is_absolute():
        raise PathNotAllowedError(f"Path must be absolute: {path}")
    resolved = path.resolve()
    root_resolved = workspace_root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PathNotAllowedError(
            f"Path {path.name!r} is outside the allowed workspace"
        ) from exc
    return resolved


@contextlib.contextmanager
def undo_bracket(name: str) -> Generator[None, None, None]:
    """Context manager that wraps an operation in an Allplan undo bracket.

    On success: commits the bracket.
    On exception: rolls back and re-raises.

    Uses the real Allplan undo API when available; no-ops gracefully when
    running outside Allplan (e.g. in tests with the fake API).
    """
    try:
        from allplan_agent.handlers._allplan import AllplanElements
        begin = getattr(AllplanElements, "BeginUndoBracket", None)
        commit = getattr(AllplanElements, "CommitUndoBracket", None)
        rollback = getattr(AllplanElements, "RollbackUndoBracket", None)
    except ImportError:
        begin = commit = rollback = None

    if begin is not None:
        begin(name)
    try:
        yield
    except Exception:
        if rollback is not None:
            try:
                rollback(name)
            except Exception:
                _log.exception("undo_bracket.rollback_failed", extra={"cmd": name})
        raise
    else:
        if commit is not None:
            commit(name)
