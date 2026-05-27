#!/usr/bin/env python3
"""Install the Allplan MCP Bridge PythonPart into Allplan's user directories.

Usage:
    python scripts/install_pythonpart.py [--scripts-dir <path>] [--library-dir <path>]
                                         [--pipe-name <name>] [--tcp-port <port>]

Run from the repository root. Requires Python 3.12+. Does NOT require the
allplan-mcp-bridge package to be installed.

The script:
  1. Locates Allplan's PythonPartsScripts and Library directories (auto-detect or explicit).
  2. Copies src/allplan_agent/ and the vendored models package into PythonPartsScripts.
  3. Writes bridge_config.json next to the agent code.
  4. Writes AllplanMcpBridge.pyp into the Library directory.
  5. Is idempotent: re-running is safe and only updates files that changed.

Does NOT install pip packages into Allplan's embedded Python.
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
_SECURITY_SRC = _REPO_ROOT / "src" / "allplan_mcp_server" / "security.py"

_ALLPLAN_VERSIONS = ["2026", "2025", "2024", "2024-1"]


def _user_allplan_roots() -> list[Path]:
    """Candidate Usr/Local roots under the Windows user Documents folder."""
    userprofile = os.environ.get("USERPROFILE", "")
    docs = Path(userprofile) / "Documents" if userprofile else Path.home() / "Documents"
    return [
        docs / "Nemetschek" / "Allplan" / ver / "Usr" / "Local"
        for ver in _ALLPLAN_VERSIONS
    ]


def _detect_scripts_dir() -> Path | None:
    """Return first existing PythonPartsScripts directory, or None."""
    if platform.system() != "Windows":
        return None
    for root in _user_allplan_roots():
        candidate = root / "PythonPartsScripts"
        if candidate.exists():
            return candidate
    return None


def _detect_library_dir() -> Path | None:
    """Return first existing Library directory, or None."""
    if platform.system() != "Windows":
        return None
    for root in _user_allplan_roots():
        candidate = root / "Library"
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


def _write_bridge_config(agent_dir: Path, pipe_name: str, tcp_port: int) -> bool:
    """Write bridge_config.json into agent_dir. Returns True if created/updated."""
    config: dict[str, object] = {
        "pipe_name": pipe_name,
        "tcp_host": "127.0.0.1",
        "tcp_port": tcp_port,
        "request_timeout": 10.0,
        # pywin32 is not bundled with Allplan 2026; force TCP so the bridge
        # starts reliably without it. Users with pywin32 can set this to false.
        "force_tcp": True,
    }
    config_path = agent_dir / "bridge_config.json"
    new_content = json.dumps(config, indent=2)
    if config_path.exists() and config_path.read_text(encoding="utf-8") == new_content:
        return False
    config_path.write_text(new_content, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Vendor models
# ---------------------------------------------------------------------------


def _vendor_models(agent_dir: Path) -> tuple[int, int]:
    """Copy allplan_mcp_server/models/ so handlers can 'from allplan_mcp_server.models import ...'

    Copies into allplan_mcp_server/models/ directly (no symlinks — Windows compatibility).
    """
    shim_pkg = agent_dir / "allplan_mcp_server"
    shim_init = shim_pkg / "__init__.py"
    models_dst = shim_pkg / "models"

    shim_pkg.mkdir(parents=True, exist_ok=True)
    models_dst.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0

    if not shim_init.exists():
        shim_init.write_text("# Vendored shim — do not edit\n", encoding="utf-8")
        copied += 1

    c2, s2 = _copy_tree(_MODELS_SRC, models_dst)
    copied += c2
    skipped += s2

    # Also vendor security.py — handlers/ifc.py imports it
    security_dst = shim_pkg / "security.py"
    if _copy_if_changed(_SECURITY_SRC, security_dst):
        copied += 1
    else:
        skipped += 1

    return copied, skipped


# ---------------------------------------------------------------------------
# PYP companion file (goes in Library, not with scripts)
# ---------------------------------------------------------------------------

_PYP_TEMPLATE = """\
<?xml version="1.0" encoding="utf-8"?>
<Element>
    <Script>
        <Name>allplan_agent\\AllplanMcpBridge.py</Name>
        <Title>Allplan MCP Bridge</Title>
        <Version>1</Version>
        <Interactor>True</Interactor>
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


def _write_pyp(library_dir: Path) -> bool:
    """Write AllplanMcpBridge.pyp into library_dir/Allplan MCP Bridge/."""
    pyp_dir = library_dir / "Allplan MCP Bridge"
    pyp_path = pyp_dir / "AllplanMcpBridge.pyp"
    if pyp_path.exists() and pyp_path.read_text(encoding="utf-8") == _PYP_TEMPLATE:
        return False
    pyp_dir.mkdir(parents=True, exist_ok=True)
    pyp_path.write_text(_PYP_TEMPLATE, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Main install function
# ---------------------------------------------------------------------------


def install(
    scripts_dir: Path,
    library_dir: Path,
    pipe_name: str,
    tcp_port: int,
) -> None:
    """Perform the installation."""
    if not _AGENT_SRC.exists():
        print(f"ERROR: Agent source not found at {_AGENT_SRC}")
        sys.exit(1)
    if not _MODELS_SRC.exists():
        print(f"ERROR: Models source not found at {_MODELS_SRC}")
        sys.exit(1)

    agent_dst = scripts_dir / "allplan_agent"
    print(f"Installing agent code into: {agent_dst}")
    agent_dst.mkdir(parents=True, exist_ok=True)

    print("Copying allplan_agent/...")
    copied, skipped = _copy_tree(_AGENT_SRC, agent_dst)
    print(f"  {copied} file(s) updated, {skipped} unchanged")

    print("Vendoring allplan_mcp_server/models/...")
    c2, s2 = _vendor_models(agent_dst)
    print(f"  {c2} file(s) updated, {s2} unchanged")

    print("Writing bridge_config.json...")
    changed = _write_bridge_config(agent_dst, pipe_name, tcp_port)
    print("  updated" if changed else "  unchanged")

    print("Writing AllplanMcpBridge.pyp...")
    changed = _write_pyp(library_dir)
    print("  created/updated" if changed else "  unchanged")

    print()
    print("Installation complete.")
    print(f"  Agent code : {agent_dst}")
    print(f"  Config     : {agent_dst / 'bridge_config.json'}")
    print(f"  PYP file   : {library_dir / 'Allplan MCP Bridge' / 'AllplanMcpBridge.pyp'}")
    print()
    print("Next steps:")
    print("  1. Start (or restart) Allplan 2026.")
    print("  2. In the Allplan Library, activate 'Allplan MCP Bridge > AllplanMcpBridge'.")
    print("  3. Start the MCP server: python -m allplan_mcp_server")
    print("  4. Configure Claude Code to use this MCP server (see docs/installation.md).")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Install Allplan MCP Bridge PythonPart")
    parser.add_argument(
        "--scripts-dir",
        type=Path,
        default=None,
        help="Allplan PythonPartsScripts directory. Auto-detected on Windows if omitted.",
    )
    parser.add_argument(
        "--library-dir",
        type=Path,
        default=None,
        help="Allplan Library directory. Auto-detected on Windows if omitted.",
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

    scripts_dir: Path | None = args.scripts_dir
    library_dir: Path | None = args.library_dir

    if scripts_dir is None:
        scripts_dir = _detect_scripts_dir()
    if library_dir is None:
        library_dir = _detect_library_dir()

    if scripts_dir is None or library_dir is None:
        roots = [str(r) for r in _user_allplan_roots()]
        print(
            "ERROR: Could not auto-detect Allplan directories.\n"
            "Pass --scripts-dir and --library-dir explicitly.\n"
            f"Checked under: {roots}"
        )
        sys.exit(1)

    install(
        scripts_dir=scripts_dir,
        library_dir=library_dir,
        pipe_name=args.pipe_name,
        tcp_port=args.tcp_port,
    )


if __name__ == "__main__":
    main()
