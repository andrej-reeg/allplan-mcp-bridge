"""Tests for scripts/install_pythonpart.py — idempotency and copy logic.

These run on any platform (no Allplan, no Windows required). The install
function accepts scripts_dir/library_dir so we can point it at tmp_path.
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


@pytest.fixture()
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    """Return (scripts_dir, library_dir) under tmp_path."""
    return tmp_path / "scripts", tmp_path / "library"


def _install(mod: object, scripts_dir: Path, library_dir: Path, **kwargs: object) -> None:
    mod.install(  # type: ignore[union-attr]
        scripts_dir=scripts_dir,
        library_dir=library_dir,
        pipe_name=kwargs.get("pipe_name", r"\\.\pipe\test-bridge"),
        tcp_port=int(kwargs.get("tcp_port", 49153)),
    )


# ---------------------------------------------------------------------------
# install() happy path
# ---------------------------------------------------------------------------


def test_install_creates_agent_directory(install_mod: object, dirs: tuple[Path, Path]) -> None:
    scripts_dir, library_dir = dirs
    _install(install_mod, scripts_dir, library_dir)
    assert (scripts_dir / "allplan_agent").is_dir()


def test_install_creates_bridge_config(install_mod: object, dirs: tuple[Path, Path]) -> None:
    scripts_dir, library_dir = dirs
    _install(
        install_mod, scripts_dir, library_dir,
        pipe_name=r"\\.\pipe\test-bridge", tcp_port=49153,
    )
    config_path = scripts_dir / "allplan_agent" / "bridge_config.json"
    assert config_path.exists()
    config = json.loads(config_path.read_text())
    assert config["pipe_name"] == r"\\.\pipe\test-bridge"
    assert config["tcp_port"] == 49153
    assert config["tcp_host"] == "127.0.0.1"


def test_install_copies_allplan_mcp_bridge_entry(
    install_mod: object, dirs: tuple[Path, Path]
) -> None:
    scripts_dir, library_dir = dirs
    _install(install_mod, scripts_dir, library_dir)
    assert (scripts_dir / "allplan_agent" / "AllplanMcpBridge.py").exists()


def test_install_copies_pythonpart_entry(install_mod: object, dirs: tuple[Path, Path]) -> None:
    scripts_dir, library_dir = dirs
    _install(install_mod, scripts_dir, library_dir)
    assert (scripts_dir / "allplan_agent" / "pythonpart_entry.py").exists()


def test_install_creates_pyp_file(install_mod: object, dirs: tuple[Path, Path]) -> None:
    scripts_dir, library_dir = dirs
    _install(install_mod, scripts_dir, library_dir)
    pyp = library_dir / "Allplan MCP Bridge" / "AllplanMcpBridge.pyp"
    assert pyp.exists()
    content = pyp.read_text(encoding="utf-8")
    assert "Allplan MCP Bridge" in content
    assert "allplan_agent" in content
    assert "AllplanMcpBridge.py" in content
    assert "Interactor" in content


def test_install_vendors_models(install_mod: object, dirs: tuple[Path, Path]) -> None:
    scripts_dir, library_dir = dirs
    _install(install_mod, scripts_dir, library_dir)
    models_dir = scripts_dir / "allplan_agent" / "allplan_mcp_server" / "models"
    assert models_dir.is_dir()
    assert (models_dir / "geometry.py").exists()
    assert (models_dir / "ifc.py").exists()


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_install_idempotent_no_changes(install_mod: object, dirs: tuple[Path, Path]) -> None:
    """Second install run with same args must not overwrite any files."""
    scripts_dir, library_dir = dirs
    _install(install_mod, scripts_dir, library_dir)

    def _mtimes() -> dict[str, float]:
        return {
            str(p.relative_to(scripts_dir.parent)): p.stat().st_mtime
            for p in list(scripts_dir.rglob("*")) + list(library_dir.rglob("*"))
            if p.is_file() and p.suffix not in (".pyc",)
        }

    mtimes_before = _mtimes()
    _install(install_mod, scripts_dir, library_dir)
    mtimes_after = _mtimes()

    for path, mtime in mtimes_before.items():
        assert mtimes_after.get(path) == mtime, f"File unexpectedly updated: {path}"


def test_install_updates_changed_config(install_mod: object, dirs: tuple[Path, Path]) -> None:
    """Second install with different pipe_name updates bridge_config.json."""
    scripts_dir, library_dir = dirs
    _install(install_mod, scripts_dir, library_dir, pipe_name=r"\\.\pipe\first")
    _install(install_mod, scripts_dir, library_dir, pipe_name=r"\\.\pipe\second")
    config = json.loads(
        (scripts_dir / "allplan_agent" / "bridge_config.json").read_text()
    )
    assert config["pipe_name"] == r"\\.\pipe\second"


def test_install_updates_modified_source_file(install_mod: object, dirs: tuple[Path, Path]) -> None:
    """If a source file changes, the installed copy is updated on re-install."""
    scripts_dir, library_dir = dirs
    _install(install_mod, scripts_dir, library_dir)

    target_file = scripts_dir / "allplan_agent" / "pythonpart_entry.py"
    original = target_file.read_bytes()
    target_file.write_bytes(b"# corrupted\n")

    _install(install_mod, scripts_dir, library_dir)
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
