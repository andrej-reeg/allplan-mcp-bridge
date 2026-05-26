"""Path allowlist and input size guards."""

from pathlib import Path


class PathNotAllowedError(ValueError):
    """Raised when a path falls outside the allowed workspace root."""


def validate_path(path: Path, workspace_root: Path) -> Path:
    """Resolve path and verify it is inside workspace_root.

    Rejects: relative paths, paths resolving outside root (including ..
    traversal), symlinks pointing outside root.
    Returns the resolved absolute path.
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
