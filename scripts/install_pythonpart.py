#!/usr/bin/env python3
"""Install the Allplan MCP Bridge PythonPart into Allplan's PythonParts directory.

Usage:
    python scripts/install_pythonpart.py [--target-dir <path>] [--pipe-name <name>]

Run from the repository root. Requires Python 3.12+. Does NOT require the
allplan-mcp-bridge package to be installed.

The script:
  1. Locates the Allplan PythonParts directory (auto-detect or --target-dir).
  2. Copies src/allplan_agent/ and the vendored models package.
  3. Writes bridge_config.json next to the agent code.
  4. Is idempotent: re-running is safe and only updates files that changed.

Does NOT install pip packages into Allplan's embedded Python. If additional
packages are needed, the user will be prompted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENT_SRC = _REPO_ROOT / "src" / "allplan_agent"
_MODELS_SRC = _REPO_ROOT / "src" / "allplan_mcp_server" / "models"

_ALLPLAN_VERSIONS = ["2026", "2025", "2024", "2024-1"]

# Common Allplan PythonParts root locations on Windows
_WINDOWS_ROOTS = [
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "Nemetschek"
    / "Allplan"
    / ver
    / "PythonParts"
    for ver in _ALLPLAN_VERSIONS
]


def _detect_pythonparts_dir() -> Path | None:
    """Return the first existing Allplan PythonParts directory, or None."""
    if platform.system() != "Windows":
        return None
    for candidate in _WINDOWS_ROOTS:
        if candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# File copy with idempotency check
# ---------------------------------------------------------------------------


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _copy_if_changed(src: Path, dst: Path) -> bool:
    """Copy src to dst only if dst doesn't exist or differs. Returns True if copied."""
    if dst.exists() and _file_hash(src) == _file_hash(dst):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_tree(src_dir: Path, dst_dir: Path) -> tuple[int, int]:
    """Recursively copy src_dir → dst_dir. Returns (copied, skipped) counts."""
    copied = 0
    skipped = 0
    for src_file in src_dir.rglob("*"):
        if src_file.is_dir():
            continue
        if src_file.suffix in (".pyc",) or src_file.name == "__pycache__":
            continue
        rel = src_file.relative_to(src_dir)
        dst_file = dst_dir / rel
        if _copy_if_changed(src_file, dst_file):
            print(f"  [copy]   {rel}")
            copied += 1
        else:
            skipped += 1
    return copied, skipped


# ---------------------------------------------------------------------------
# bridge_config.json
# ---------------------------------------------------------------------------


def _write_bridge_config(target_dir: Path, pipe_name: str, tcp_port: int) -> bool:
    """Write bridge_config.json. Returns True if file was created/updated."""
    config: dict[str, object] = {
        "pipe_name": pipe_name,
        "tcp_host": "127.0.0.1",
        "tcp_port": tcp_port,
        "request_timeout": 10.0,
    }
    config_path = target_dir / "allplan_agent" / "bridge_config.json"
    new_content = json.dumps(config, indent=2)
    if config_path.exists() and config_path.read_text(encoding="utf-8") == new_content:
        return False
    config_path.write_text(new_content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Vendor models
# ---------------------------------------------------------------------------


def _vendor_models(target_agent_dir: Path) -> tuple[int, int]:
    """Copy allplan_mcp_server/models/ into the agent directory as a vendored sub-package."""
    dst = target_agent_dir / "allplan_mcp_server_models"
    copied, skipped = _copy_tree(_MODELS_SRC, dst)
    # Write a bridge __init__.py so it's importable as allplan_mcp_server.models
    # The agent's handlers import from allplan_mcp_server.models; we create a
    # shim package so those imports resolve without installing the server package.
    shim_init = target_agent_dir / "allplan_mcp_server" / "__init__.py"
    shim_models = target_agent_dir / "allplan_mcp_server" / "models"
    shim_init.parent.mkdir(parents=True, exist_ok=True)
    if not shim_init.exists():
        shim_init.write_text("# Vendored shim — do not edit\n", encoding="utf-8")
        copied += 1
    # Symlink or copy models into the shim package
    if not shim_models.exists():
        shim_models.symlink_to(dst)
        copied += 1
    return copied, skipped


# ---------------------------------------------------------------------------
# PYP companion file
# ---------------------------------------------------------------------------

_PYP_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<Element>
    <Script>
        <Name>allplan_agent.pythonpart_entry</Name>
        <Title>Allplan MCP Bridge</Title>
        <Version>1</Version>
    </Script>
    <Page>
        <Name>Page1</Name>
        <Text>MCP Bridge</Text>
        <Parameter>
            <Name>Info</Name>
            <Text>Status</Text>
            <Value>Use Claude Code to control Allplan over MCP.</Value>
            <ValueType>String</ValueType>
        </Parameter>
    </Page>
</Element>
"""


def _write_pyp(target_dir: Path) -> bool:
    pyp_path = target_dir / "AllplanMcpBridge.pyp"
    if pyp_path.exists():
        return False
    pyp_path.write_text(_PYP_TEMPLATE, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def install(
    target_dir: Path,
    pipe_name: str,
    tcp_port: int,
) -> None:
    """Perform the installation into target_dir."""
    if not _AGENT_SRC.exists():
        print(f"ERROR: Agent source not found at {_AGENT_SRC}")
        sys.exit(1)
    if not _MODELS_SRC.exists():
        print(f"ERROR: Models source not found at {_MODELS_SRC}")
        sys.exit(1)

    print(f"Installing into: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    print("Copying allplan_agent/...")
    copied, skipped = _copy_tree(_AGENT_SRC, target_dir / "allplan_agent")
    print(f"  {copied} file(s) updated, {skipped} unchanged")

    print("Vendoring allplan_mcp_server/models/...")
    c2, s2 = _vendor_models(target_dir)
    print(f"  {c2} file(s) updated, {s2} unchanged")

    print("Writing bridge_config.json...")
    changed = _write_bridge_config(target_dir, pipe_name, tcp_port)
    print("  updated" if changed else "  unchanged")

    print("Writing AllplanMcpBridge.pyp...")
    changed = _write_pyp(target_dir)
    print("  created" if changed else "  already exists")

    print()
    print("Installation complete.")
    print(f"  Agent code : {target_dir / 'allplan_agent'}")
    print(f"  Config     : {target_dir / 'allplan_agent' / 'bridge_config.json'}")
    print(f"  PYP file   : {target_dir / 'AllplanMcpBridge.pyp'}")
    print()
    print("Next steps:")
    print("  1. Start Allplan 2026.")
    print("  2. In the Allplan toolbox, activate 'AllplanMcpBridge'.")
    print("  3. Start the MCP server: python -m allplan_mcp_server")
    print("  4. Configure Claude Code to use this MCP server (see docs/installation.md).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Allplan MCP Bridge PythonPart")
    parser.add_argument(
        "--target-dir",
        type=Path,
        default=None,
        help="PythonParts installation directory. Auto-detected on Windows if omitted.",
    )
    parser.add_argument(
        "--pipe-name",
        default=r"\\.\pipe\allplan-mcp-bridge",
        help=r"Named pipe name (Windows). Default: \\.\pipe\allplan-mcp-bridge",
    )
    parser.add_argument(
        "--tcp-port",
        type=int,
        default=49152,
        help="TCP port for loopback fallback transport. Default: 49152",
    )
    args = parser.parse_args()

    target_dir: Path | None = args.target_dir
    if target_dir is None:
        target_dir = _detect_pythonparts_dir()
    if target_dir is None:
        print(
            "ERROR: Could not auto-detect Allplan PythonParts directory.\n"
            "Pass --target-dir <path> explicitly.\n"
            f"Checked: {[str(p) for p in _WINDOWS_ROOTS]}"
        )
        sys.exit(1)

    install(
        target_dir=target_dir,
        pipe_name=args.pipe_name,
        tcp_port=args.tcp_port,
    )


if __name__ == "__main__":
    main()
