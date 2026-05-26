from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALLPLAN_MCP_", env_file=".env")

    ipc_transport: Literal["named_pipe", "tcp"] = "named_pipe"
    # {session_id} is a template placeholder — the IPC layer substitutes it at runtime
    pipe_name: str = r"\\.\pipe\allplan-mcp-{session_id}"
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 49152
    tcp_token_file: Path = Path("~/.allplan-mcp/token")
    tcp_token: SecretStr = SecretStr("")
    request_timeout_seconds: float = 10.0
    long_op_timeout_seconds: float = 120.0
    allplan_workspace_root: Path
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _load_tcp_token(self) -> "Settings":
        resolved = self.tcp_token_file.expanduser()
        if resolved.exists():
            self.tcp_token = SecretStr(resolved.read_text().strip())
        return self

    @field_validator("tcp_port")
    @classmethod
    def _validate_tcp_port(cls, v: int) -> int:
        if not (1024 <= v <= 65535):
            raise ValueError(f"tcp_port must be 1024–65535, got {v}")
        return v

    @field_validator("allplan_workspace_root")
    @classmethod
    def _normalize_workspace_root(cls, v: Path) -> Path:
        return v.resolve()

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        upper = v.upper()
        if upper not in _VALID_LOG_LEVELS:
            raise ValueError(f"log_level must be one of {_VALID_LOG_LEVELS}, got {v!r}")
        return upper
