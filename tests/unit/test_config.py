import pytest
from pydantic import ValidationError

from allplan_mcp_server.config import Settings


def test_settings_raises_without_workspace() -> None:
    with pytest.raises((ValidationError, Exception)):
        Settings()


def test_settings_with_workspace(tmp_path: pytest.TempPathFactory) -> None:
    s = Settings(allplan_workspace_root=tmp_path)  # type: ignore[arg-type]
    assert s.ipc_transport == "named_pipe"
    assert s.request_timeout_seconds == 10.0
    assert s.log_level == "INFO"


def test_invalid_log_level(tmp_path: pytest.TempPathFactory) -> None:
    with pytest.raises(ValidationError):
        Settings(allplan_workspace_root=tmp_path, log_level="VERBOSE")  # type: ignore[arg-type]


def test_invalid_tcp_port(tmp_path: pytest.TempPathFactory) -> None:
    with pytest.raises(ValidationError):
        Settings(allplan_workspace_root=tmp_path, tcp_port=80)  # type: ignore[arg-type]


def test_tcp_token_loaded_from_file(tmp_path: pytest.TempPathFactory) -> None:
    token_file = tmp_path / "token"  # type: ignore[operator]
    token_file.write_text("secret-token")
    s = Settings(
        allplan_workspace_root=tmp_path,  # type: ignore[arg-type]
        tcp_token_file=token_file,
    )
    assert s.tcp_token.get_secret_value() == "secret-token"
