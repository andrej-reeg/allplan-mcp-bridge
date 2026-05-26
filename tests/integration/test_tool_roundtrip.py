"""Integration tests: full IPC roundtrip through real dispatcher + fake Allplan API."""

import pytest

from allplan_mcp_server.ipc.client import IpcClient


async def test_create_wall_roundtrip(agent_client: IpcClient) -> None:
    result = await agent_client.call(
        "create_wall",
        {
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 5000, "y": 0, "z": 0},
            "height_mm": 2800,
            "thickness_mm": 200,
        },
        timeout=5.0,
    )
    assert result["kind"] == "wall"
    assert isinstance(result["uuid"], str)


async def test_create_and_get_element(agent_client: IpcClient) -> None:
    ref = await agent_client.call(
        "create_wall",
        {
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 3000, "y": 0, "z": 0},
            "height_mm": 2500,
            "thickness_mm": 150,
        },
        timeout=5.0,
    )
    got = await agent_client.call(
        "get_element", {"uuid": ref["uuid"], "kind": "wall"}, timeout=5.0
    )
    assert got["uuid"] == ref["uuid"]


async def test_delete_element(agent_client: IpcClient) -> None:
    ref = await agent_client.call(
        "create_wall",
        {
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 4000, "y": 0, "z": 0},
            "height_mm": 3000,
            "thickness_mm": 200,
        },
        timeout=5.0,
    )
    result = await agent_client.call(
        "delete_element", {"uuid": ref["uuid"], "kind": "wall"}, timeout=5.0
    )
    assert result["deleted"] is True


async def test_set_and_get_attributes(agent_client: IpcClient) -> None:
    ref = await agent_client.call(
        "create_wall",
        {
            "start": {"x": 0, "y": 0, "z": 0},
            "end": {"x": 4000, "y": 0, "z": 0},
            "height_mm": 3000,
            "thickness_mm": 200,
        },
        timeout=5.0,
    )
    await agent_client.call(
        "set_attributes",
        {
            "uuid": ref["uuid"],
            "kind": "wall",
            "attributes": [{"name": "Material", "value": "Concrete"}],
        },
        timeout=5.0,
    )
    attrs = await agent_client.call(
        "get_attributes", {"uuid": ref["uuid"], "kind": "wall"}, timeout=5.0
    )
    assert attrs["attributes"]["Material"] == "Concrete"


async def test_layer_lifecycle(agent_client: IpcClient) -> None:
    await agent_client.call("create_layer", {"name": "STRUCT"}, timeout=5.0)
    layers = await agent_client.call("list_layers", {}, timeout=5.0)
    names = [lay["name"] for lay in layers["layers"]]
    assert "STRUCT" in names

    vis = await agent_client.call(
        "set_layer_visibility", {"name": "STRUCT", "visible": False}, timeout=5.0
    )
    assert vis["visible"] is False


async def test_document_save_and_undo_redo(agent_client: IpcClient) -> None:
    info = await agent_client.call("get_active_document_info", {}, timeout=5.0)
    assert "name" in info

    saved = await agent_client.call("save_document", {}, timeout=5.0)
    assert saved["saved"] is True

    assert (await agent_client.call("undo", {}, timeout=5.0))["ok"] is True
    assert (await agent_client.call("redo", {}, timeout=5.0))["ok"] is True


async def test_unknown_command_returns_error(agent_client: IpcClient) -> None:
    from allplan_mcp_server.ipc.client import IpcError

    with pytest.raises(IpcError):
        await agent_client.call("no_such_command", {}, timeout=5.0)


async def test_concurrent_requests(agent_client: IpcClient) -> None:
    import anyio

    results = []

    async def _make_wall(n: int) -> None:
        r = await agent_client.call(
            "create_wall",
            {
                "start": {"x": n * 100.0, "y": 0, "z": 0},
                "end": {"x": n * 100.0 + 5000, "y": 0, "z": 0},
                "height_mm": 2800,
                "thickness_mm": 200,
            },
            timeout=5.0,
        )
        results.append(r["uuid"])

    async with anyio.create_task_group() as tg:
        for i in range(5):
            tg.start_soon(_make_wall, i)

    assert len(results) == 5
    assert len(set(results)) == 5  # all UUIDs distinct
