"""Entry point: initialise IPC client, register tools, run FastMCP over stdio."""

import anyio

from . import server
from . import tools as _tools_pkg  # noqa: F401 — side-effect: registers all tools on mcp
from .config import Settings
from .ipc.client import IpcClient
from .ipc.tcp import TcpTransport
from .logging import configure_logging
from .server import mcp


def _make_client(settings: Settings) -> IpcClient:
    if settings.ipc_transport == "tcp":
        # Read token fresh on each connection — bridge regenerates on every restart.
        token_file = settings.tcp_token_file.expanduser()

        def _tcp_factory() -> TcpTransport:
            token = token_file.read_text(encoding="utf-8").strip() if token_file.exists() else ""
            return TcpTransport(
                host=settings.tcp_host,
                port=settings.tcp_port,
                token=token,
            )

        return IpcClient(_tcp_factory, max_arg_bytes=settings.max_arg_bytes)

    from .ipc.named_pipe import NamedPipeTransport

    pipe_name = settings.pipe_name

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
