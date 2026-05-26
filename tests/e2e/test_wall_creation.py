"""E2E tests requiring a live Allplan instance and running MCP server.

Gated by ALLPLAN_MCP_E2E=1. Skipped in CI.

These tests assume:
- Allplan 2026 is running with the MCP bridge PythonPart active.
- The MCP server is running (python -m allplan_mcp_server).
- ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT is set to a writable directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from allplan_mcp_server.ipc.client import IpcClient

pytestmark = pytest.mark.skipif(
    os.environ.get("ALLPLAN_MCP_E2E") != "1",
    reason="Set ALLPLAN_MCP_E2E=1 to run end-to-end tests (requires Allplan)",
)


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = os.environ.get("ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT")
    if root:
        return Path(root)
    return tmp_path_factory.mktemp("allplan_ws")


@pytest.fixture(scope="module")
def ipc_client() -> object:
    """Return a connected IpcClient for the running MCP server."""
    import anyio

    from allplan_mcp_server.config import Settings
    from allplan_mcp_server.ipc.client import IpcClient as _IpcClient
    from allplan_mcp_server.ipc.tcp import TcpTransport

    settings = Settings()  # type: ignore[call-arg]

    def _factory() -> TcpTransport:
        return TcpTransport(
            host=settings.tcp_host,
            port=settings.tcp_port,
            token=settings.tcp_token.get_secret_value(),
        )

    client = _IpcClient(_factory)
    anyio.run(client.start)
    yield client
    anyio.run(client.stop)


@pytest.mark.requires_allplan
def test_create_wall_returns_element_ref(ipc_client: object) -> None:
    """create_wall returns an ElementRef with a valid UUID."""
    import anyio

    client: IpcClient = ipc_client  # type: ignore[assignment]

    async def _run() -> dict[str, object]:
        return await client.call(
            "create_wall",
            {
                "start": {"x": 0.0, "y": 0.0, "z": 0.0},
                "end": {"x": 5000.0, "y": 0.0, "z": 0.0},
                "height_mm": 3000.0,
                "thickness_mm": 300.0,
            },
            timeout=15.0,
        )

    result = anyio.run(_run)
    assert "uuid" in result
    assert len(str(result["uuid"])) > 0


@pytest.mark.requires_allplan
def test_set_attributes_on_created_wall(ipc_client: object) -> None:
    """set_attributes updates an element's attributes."""
    import anyio

    client: IpcClient = ipc_client  # type: ignore[assignment]

    async def _create() -> str:
        r = await client.call(
            "create_wall",
            {
                "start": {"x": 1000.0, "y": 0.0, "z": 0.0},
                "end": {"x": 3000.0, "y": 0.0, "z": 0.0},
                "height_mm": 3000.0,
                "thickness_mm": 200.0,
            },
            timeout=15.0,
        )
        return str(r["uuid"])

    async def _set(uuid: str) -> dict[str, object]:
        return await client.call(
            "set_attributes",
            {
                "uuid": uuid,
                "kind": "wall",
                "attributes": [{"name": "FireRating", "value": "F30"}],
            },
            timeout=10.0,
        )

    uuid = anyio.run(_create)
    result = anyio.run(lambda: _set(uuid))
    assert result.get("updated") == 1


@pytest.mark.requires_allplan
def test_export_and_import_ifc_roundtrip(ipc_client: object, workspace: Path) -> None:
    """export_ifc writes a file; import_ifc reads it back."""
    import anyio

    client: IpcClient = ipc_client  # type: ignore[assignment]
    ifc_path = workspace / "roundtrip.ifc"

    async def _export() -> dict[str, object]:
        return await client.call(
            "export_ifc",
            {"path": str(ifc_path), "schema_version": "IFC4"},
            timeout=120.0,
        )

    async def _import() -> dict[str, object]:
        return await client.call(
            "import_ifc",
            {"path": str(ifc_path)},
            timeout=120.0,
        )

    export_result = anyio.run(_export)
    assert export_result.get("exported") is True
    assert ifc_path.exists(), "IFC file not created"

    import_result = anyio.run(_import)
    assert isinstance(import_result.get("imported"), int)
    assert import_result["imported"] >= 0
