"""Shared fixtures for integration tests.

The `agent_client` fixture starts a FakeAgent on a random TCP port and
returns a connected IpcClient. All integration tests run against this fake
instead of a real Allplan installation.
"""

import asyncio
import contextlib
from collections.abc import AsyncGenerator

import pytest

from allplan_mcp_server.ipc.client import IpcClient
from allplan_mcp_server.ipc.tcp import TcpTransport
from tests.fakes.fake_agent import FakeAgent
from tests.fakes.fake_allplan_api import reset_all

_TOKEN = "integration-test-token"


@pytest.fixture(autouse=True)
def _reset_fake_state() -> None:
    reset_all()


@pytest.fixture
async def agent_client() -> AsyncGenerator[IpcClient, None]:
    agent = FakeAgent(token=_TOKEN)
    started: asyncio.Event = asyncio.Event()

    # Use asyncio.create_task (not anyio task group) so the cancel scope
    # stays in one task and doesn't trip anyio's cross-task check on teardown.
    bg_task = asyncio.create_task(agent.serve_asyncio(started))
    await started.wait()

    client = IpcClient(
        lambda: TcpTransport(host="127.0.0.1", port=agent.port, token=_TOKEN)
    )
    await client.start()

    yield client

    await client.stop()
    bg_task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await bg_task
