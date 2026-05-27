"""Health MCP tool: server and agent status, per-tool metrics."""

from __future__ import annotations

import time
from typing import Any

import structlog

from ..metrics import get_metrics
from ..server import get_client, mcp

log = structlog.get_logger(__name__)

try:
    from importlib.metadata import version as _pkg_version

    _VERSION: str = _pkg_version("allplan-mcp-bridge")
except Exception:
    _VERSION = "dev"


@mcp.tool
async def health() -> dict[str, Any]:
    """Return server and agent health status.

    Reports: agent connection state, last heartbeat age (ms), queue depth,
    reconnect count since server start, and per-tool call/error counts with
    p50/p95/p99 latencies over the last 1000 samples.
    Read-only — no side effects on the Allplan document.
    """
    client = get_client()
    heartbeat_age_ms = int((time.monotonic() - client._last_heartbeat_at) * 1000)

    return {
        "server_ok": True,
        "agent_connected": client.is_connected,
        "last_heartbeat_age_ms": heartbeat_age_ms,
        "queue_depth": client._last_queue_depth,
        "reconnect_count": client._reconnect_count,
        "version": _VERSION,
        "tools": get_metrics().summary(),
    }
