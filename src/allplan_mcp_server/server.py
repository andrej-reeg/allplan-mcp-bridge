"""FastMCP server instance and module-level state accessors."""

from fastmcp import FastMCP

from .config import Settings
from .ipc.client import IpcClient

mcp: FastMCP = FastMCP("allplan-bridge")

_client: IpcClient | None = None
_settings: Settings | None = None


def init(client: IpcClient, settings: Settings) -> None:
    global _client, _settings
    _client = client
    _settings = settings


def get_client() -> IpcClient:
    if _client is None:
        raise RuntimeError("IpcClient not initialised — call server.init() first")
    return _client


def get_settings() -> Settings:
    if _settings is None:
        raise RuntimeError("Settings not initialised — call server.init() first")
    return _settings
