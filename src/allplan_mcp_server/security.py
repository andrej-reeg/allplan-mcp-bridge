"""Path allowlist and input size guards."""

import json
from pathlib import Path
from typing import Any


class PathNotAllowedError(ValueError):
    """Raised when a path falls outside the allowed workspace root."""


class ArgSizeTooLargeError(ValueError):
    """Raised when JSON-encoded arguments exceed the configured cap."""


def validate_path(path: Path, workspace_root: Path) -> Path:
    """Resolve path and verify it is inside workspace_root.

    Rejects: relative paths, UNC paths (Windows), paths resolving outside root
    (including .. traversal), symlinks pointing outside root.
    Returns the resolved absolute path.
    """
    path_str = str(path)

    # UNC paths (\\server\share or //server/share) are never allowed; they
    # bypass the workspace root check and may point to remote filesystems.
    if path_str.startswith("\\\\") or path_str.startswith("//"):
        raise PathNotAllowedError(f"UNC paths are not allowed: {path.name!r}")

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


def validate_arg_size(args: dict[str, Any], max_bytes: int) -> None:
    """Raise ArgSizeTooLargeError if JSON-encoded args exceed max_bytes.

    Checked before sending over IPC to guard against pathological inputs
    (deeply nested structures, huge strings) that would exhaust memory or
    time when parsed on the agent side.
    """
    try:
        encoded_len = len(json.dumps(args, separators=(",", ":")).encode())
    except (TypeError, ValueError) as exc:
        raise ArgSizeTooLargeError(f"Arguments are not JSON-serialisable: {exc}") from exc
    if encoded_len > max_bytes:
        raise ArgSizeTooLargeError(
            f"Arguments too large: {encoded_len} bytes exceeds cap of {max_bytes} bytes"
        )


def check_ifc_export_size(
    path: Path,
    warn_bytes: int,
    max_bytes: int,
) -> bool:
    """Check IFC file size after export.

    Returns True if size exceeds warn_bytes (caller should log a warning).
    Raises ValueError when size exceeds max_bytes.
    Returns False / no-ops if the file does not yet exist.
    """
    if not path.exists():
        return False
    size = path.stat().st_size
    if size > max_bytes:
        raise ValueError(
            f"IFC file {path.name!r} is {size} bytes, exceeds hard limit of {max_bytes} bytes"
        )
    return size > warn_bytes
