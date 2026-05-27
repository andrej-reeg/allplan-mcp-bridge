import os
import platform
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

_ALLPLAN_VERSIONS = ["2026", "2025", "2024", "2024-1"]

_WIN_USERS_SKIP = {"Public", "Default", "Default User", "All Users"}


def _default_tcp_token_file() -> Path:
    """In WSL2, the bridge writes the token to the Windows user profile.

    Auto-detect: scan /mnt/c/Users/<user>/.allplan-mcp/token. Falls back to the
    standard Linux home path when not running under WSL2 or when the Windows
    drive is not mounted.
    """
    if platform.system() == "Linux":
        win_users = Path("/mnt/c/Users")
        if win_users.is_dir():
            for user_dir in sorted(win_users.iterdir()):
                if user_dir.name in _WIN_USERS_SKIP or not user_dir.is_dir():
                    continue
                candidate = user_dir / ".allplan-mcp" / "token"
                if candidate.exists():
                    return candidate
            # Token not yet created; point at the first real user dir
            for user_dir in sorted(win_users.iterdir()):
                if user_dir.name in _WIN_USERS_SKIP or not user_dir.is_dir():
                    continue
                return user_dir / ".allplan-mcp" / "token"
    return Path("~/.allplan-mcp/token")


def _default_workspace_root() -> Path:
    if platform.system() == "Windows":
        docs = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents"
        for ver in _ALLPLAN_VERSIONS:
            candidate = docs / "Nemetschek" / "Allplan" / ver / "Usr" / "Local"
            if candidate.exists():
                return candidate
    return Path.home() / "allplan-workspace"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ALLPLAN_MCP_", env_file=".env")

    ipc_transport: Literal["named_pipe", "tcp"] = "tcp"
    pipe_name: str = r"\\.\pipe\allplan-mcp-bridge"
    tcp_host: str = "127.0.0.1"
    tcp_port: int = 49152
    tcp_token_file: Path = Field(default_factory=_default_tcp_token_file)
    tcp_token: SecretStr = SecretStr("")
    request_timeout_seconds: float = 10.0
    long_op_timeout_seconds: float = 120.0
    allplan_workspace_root: Path = Field(default_factory=_default_workspace_root)
    log_level: str = "INFO"
    max_frame_bytes: int = 16 * 1024 * 1024          # 16 MiB IPC frame cap
    max_arg_bytes: int = 1024 * 1024                  # 1 MiB per-tool argument cap
    ifc_export_warn_bytes: int = 100 * 1024 * 1024   # 100 MiB — log warning
    ifc_export_max_bytes: int = 1024 * 1024 * 1024   # 1 GiB — hard reject

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
            raise ValueError(f"tcp_port must be 1024-65535, got {v}")
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
