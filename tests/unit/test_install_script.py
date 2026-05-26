"""Tests for scripts/install_pythonpart.py — idempotency and copy logic.

These run on any platform (no Allplan, no Windows required). The install
function accepts a --target-dir argument so we can point it at tmp_path.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_install_module() -> object:
    """Dynamically load scripts/install_pythonpart.py without installing it."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    script = repo_root / "scripts" / "install_pythonpart.py"
    spec = importlib.util.spec_from_file_location("install_pythonpart", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def install_mod() -> object:
    return _load_install_module()


# ---------------------------------------------------------------------------
# install() happy path
# ---------------------------------------------------------------------------


def test_install_creates_agent_directory(install_mod: object, tmp_path: Path) -> None:
    install_mod.install(  # type: ignore[union-attr]
        target_dir=tmp_path,
        pipe_name=r"\\.\pipe\test-bridge",
        tcp_port=49153,
    )
    assert (tmp_path / "allplan_agent").is_dir()


def test_install_creates_bridge_config(install_mod: object, tmp_path: Path) -> None:
    install_mod.install(  # type: ignore[union-attr]
        target_dir=tmp_path,
        pipe_name=r"\\.\pipe\test-bridge",
        tcp_port=49153,
    )
    config_path = tmp_path / "allplan_agent" / "bridge_config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert config["pipe_name"] == r"\\.\pipe\test-bridge"
    assert config["tcp_port"] == 49153
    assert config["tcp_host"] == "127.0.0.1"


def test_install_copies_pythonpart_entry(install_mod: object, tmp_path: Path) -> None:
    install_mod.install(  # type: ignore[union-attr]
        target_dir=tmp_path,
        pipe_name=r"\\.\pipe\test",
        tcp_port=49152,
    )
    assert (tmp_path / "allplan_agent" / "pythonpart_entry.py").exists()


def test_install_creates_pyp_file(install_mod: object, tmp_path: Path) -> None:
    install_mod.install(  # type: ignore[union-attr]
        target_dir=tmp_path,
        pipe_name=r"\\.\pipe\test",
        tcp_port=49152,
    )
    pyp = tmp_path / "AllplanMcpBridge.pyp"
    assert pyp.exists()
    content = pyp.read_text(encoding="utf-8")
    assert "Allplan MCP Bridge" in content
    assert "allplan_agent.pythonpart_entry" in content


def test_install_vendors_models(install_mod: object, tmp_path: Path) -> None:
    install_mod.install(  # type: ignore[union-attr]
        target_dir=tmp_path,
        pipe_name=r"\\.\pipe\test",
        tcp_port=49152,
    )
    # Models vendored alongside agent code
    vendor_dir = tmp_path / "allplan_mcp_server_models"
    assert vendor_dir.is_dir()
    # Key model files present
    assert (vendor_dir / "geometry.py").exists()
    assert (vendor_dir / "ifc.py").exists()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_install_idempotent_no_changes(install_mod: object, tmp_path: Path) -> None:
    """Second install run with same args must not overwrite any files."""
    mod = install_mod

    # First run
    mod.install(target_dir=tmp_path, pipe_name=r"\\.\pipe\test", tcp_port=49152)  # type: ignore[union-attr]

    # Collect mtimes after first install
    def _mtimes() -> dict[str, float]:
        return {
            str(p.relative_to(tmp_path)): p.stat().st_mtime
            for p in tmp_path.rglob("*")
            if p.is_file() and p.suffix not in (".pyc",)
        }

    mtimes_before = _mtimes()

    # Second run — same args
    mod.install(target_dir=tmp_path, pipe_name=r"\\.\pipe\test", tcp_port=49152)  # type: ignore[union-attr]
    mtimes_after = _mtimes()

    # No file should have been updated (all hashes match → no writes)
    for path, mtime in mtimes_before.items():
        # bridge_config.json is re-evaluated but content-equal → skipped
        assert mtimes_after.get(path) == mtime, f"File unexpectedly updated: {path}"


def test_install_updates_changed_config(install_mod: object, tmp_path: Path) -> None:
    """Second install with different pipe_name updates bridge_config.json."""
    mod = install_mod
    mod.install(target_dir=tmp_path, pipe_name=r"\\.\pipe\first", tcp_port=49152)  # type: ignore[union-attr]

    # Change the pipe name
    mod.install(target_dir=tmp_path, pipe_name=r"\\.\pipe\second", tcp_port=49152)  # type: ignore[union-attr]

    config = json.loads(
        (tmp_path / "allplan_agent" / "bridge_config.json").read_text()
    )
    assert config["pipe_name"] == r"\\.\pipe\second"


def test_install_updates_modified_source_file(install_mod: object, tmp_path: Path) -> None:
    """If a source file changes, the installed copy is updated on re-install."""
    mod = install_mod
    mod.install(target_dir=tmp_path, pipe_name=r"\\.\pipe\test", tcp_port=49152)  # type: ignore[union-attr]

    # Corrupt one installed file
    target_file = tmp_path / "allplan_agent" / "pythonpart_entry.py"
    original = target_file.read_bytes()
    target_file.write_bytes(b"# corrupted\n")

    # Re-install should restore it
    mod.install(target_dir=tmp_path, pipe_name=r"\\.\pipe\test", tcp_port=49152)  # type: ignore[union-attr]
    assert target_file.read_bytes() == original


# ---------------------------------------------------------------------------
# File hash helper
# ---------------------------------------------------------------------------


def test_file_hash_deterministic(tmp_path: Path, install_mod: object) -> None:
    f = tmp_path / "test.txt"
    f.write_bytes(b"hello world")
    h1 = install_mod._file_hash(f)  # type: ignore[union-attr]
    h2 = install_mod._file_hash(f)  # type: ignore[union-attr]
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_file_hash_differs_for_different_content(tmp_path: Path, install_mod: object) -> None:
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_bytes(b"aaa")
    f2.write_bytes(b"bbb")
    assert install_mod._file_hash(f1) != install_mod._file_hash(f2)  # type: ignore[union-attr]
