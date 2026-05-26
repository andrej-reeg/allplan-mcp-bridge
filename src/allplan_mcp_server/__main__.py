"""Entry point: initialise IPC client, register tools, run FastMCP over stdio."""

import secrets
import stat

import anyio

from . import server
from . import tools as _tools_pkg  # noqa: F401 — side-effect: registers all tools on mcp
from .config import Settings
from .ipc.client import IpcClient
from .ipc.tcp import TcpTransport
from .logging import configure_logging
from .server import mcp


def _rotate_tcp_token(settings: Settings) -> str:
    """Generate a new random TCP auth token, write to token file with 0600 perms.

    Returns the new token string.
    """
    token_file = settings.tcp_token_file.expanduser()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(32)
    token_file.write_text(token)
    token_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    return token


def _make_client(settings: Settings) -> IpcClient:
    if settings.ipc_transport == "tcp":
        token = _rotate_tcp_token(settings)

        def _tcp_factory() -> TcpTransport:
            return TcpTransport(
                host=settings.tcp_host,
                port=settings.tcp_port,
                token=token,
            )

        return IpcClient(_tcp_factory, max_arg_bytes=settings.max_arg_bytes)

    from .ipc.named_pipe import NamedPipeTransport

    pipe_name = settings.pipe_name.format(session_id="default")

    def _pipe_factory() -> NamedPipeTransport:
        return NamedPipeTransport(pipe_name=pipe_name)

    return IpcClient(_pipe_factory, max_arg_bytes=settings.max_arg_bytes)


async def _amain() -> None:
    settings = Settings()  # type: ignore[call-arg]  # allplan_workspace_root comes from env
    configure_logging(
        log_level=settings.log_level,
        workspace_root=settings.allplan_workspace_root,
    )
    client = _make_client(settings)
    await client.start()
    server.init(client, settings)
    try:
        await mcp.run_async()
    finally:
        await client.stop()


def main() -> None:
    anyio.run(_amain)


if __name__ == "__main__":
    main()
