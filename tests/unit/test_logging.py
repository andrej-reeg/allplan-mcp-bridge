from pathlib import Path

from allplan_mcp_server.logging import _redact_value, configure_logging


def test_configure_logging_does_not_raise(tmp_path: Path) -> None:
    configure_logging(log_level="WARNING", workspace_root=tmp_path)


def test_path_redactor_hides_outside_paths(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    result = _redact_value("/etc/passwd", root)
    assert "etc" not in result
    assert "passwd" in result  # basename preserved


def test_path_redactor_allows_inside_paths(tmp_path: Path) -> None:
    inside = str(tmp_path / "model.ifc")
    result = _redact_value(inside, tmp_path)
    assert result == inside


def test_path_redactor_no_root(tmp_path: Path) -> None:
    result = _redact_value("/etc/passwd", None)
    assert result == "<redacted:passwd>"


def test_path_redactor_non_absolute_unchanged() -> None:
    result = _redact_value("relative/path.ifc", None)
    assert result == "relative/path.ifc"
