# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [0.1.0] — 2026-05-27

First complete release. All ten implementation phases done.

### Added

**Infrastructure (phases 1–3)**
- `pyproject.toml` with `uv`/`hatch` build, Python 3.12, pinned deps
- GitHub Actions CI: ruff, mypy --strict, pytest unit + integration, thread-safety (×20)
- Length-prefixed JSON IPC framing (`ipc/framing.py`) with 16 MiB cap
- Loopback TCP transport with HMAC token auth; Windows named-pipe transport (requires pywin32)
- `IpcClient`: request/response correlator, exponential-backoff auto-reconnect, graceful drain on shutdown
- Thread-safe `CommandQueue` (bounded 256), `pump_once()` drain loop, `@command` dispatcher

**Models (phase 4)**
- `Point3D`, `Vector3D`, `WallSpec`, `SlabSpec`, `ColumnSpec`, `BeamSpec`, `GenericSolidSpec`
- `AttributeSpec`, `LayerSpec`, `ElementRef`, `IfcExportSpec`, `IfcImportSpec`
- Validators: positive dimensions, non-degenerate geometry, finite coordinates, 10 km cap

**Handlers (phase 5)**
- Geometry: `create_wall`, `create_slab`, `create_column`, `create_beam`, `get_element`, `delete_element`, `move_element`
- Document: `get_active_document_info`, `save_document`, `undo`, `redo`
- Attributes: `get_attributes`, `set_attributes`
- Layers: `list_layers`, `create_layer`, `set_layer_visibility`, `assign_layer`
- IFC: `export_ifc`, `import_ifc`

**MCP server surface (phase 6)**
- FastMCP server with all 20 tools; strict docstrings per tool; long-op timeout for IFC

**Security (phase 7)**
- Path traversal protection (`security.validate_path`) applied to all IFC tools
- TCP HMAC token auth; token rotated on each bridge start; token file 0600
- Frame cap (16 MiB), queue cap (256), per-tool arg cap (1 MiB)
- Error responses sanitised — no stack traces or absolute paths to the MCP client

**Allplan runtime (phase 8)**
- `AllplanMcpBridge.py` PythonPart: `create_interactor`, QTimer drain, IFW callback fallback
- `scripts/install_pythonpart.py`: auto-detects Allplan dirs, copies agent, vendors models, writes `.pyp`
- Wall geometry uses `BRep3D.CreateCuboid(AxisPlacement3D, ...)` for world-space placement
- pywin32 absent in Allplan 2026 — auto-falls back to TCP; `force_tcp: true` in default config

**Observability (phase 9)**
- Per-tool metrics: call count, error count, p50/p95/p99 latency (rolling 1000 samples)
- `correlation_id` propagated through MCP server log → IPC frame → agent log
- `health` MCP tool: agent status, heartbeat age, queue depth, reconnect count, tool stats
- Graceful shutdown: `IpcClient.drain(5 s)` before `stop()` on SIGINT

**Documentation (phase 10)**
- `README.md`: quick start, architecture overview, config reference, limitations
- `docs/architecture.md`: three-process diagram, data flow, threading summary
- `docs/tool-catalog.md`: all 20 tools with schemas and examples
- `docs/ipc-protocol.md`: wire format, error codes, heartbeat spec
- `docs/threading-model.md`: the one law and every code path that enforces it
- `docs/threat-model.md`: attack surface, mitigations, scope
- `CONTRIBUTING.md`: how to add a new tool (10-box checklist)

### Fixed (during phase 8 live testing)

- Double `bg_pump` thread: removed `importlib.reload()` from `create_interactor`
- TCP token path mismatch between Allplan (Windows) and MCP server (WSL2)
- `get_active_document_info` deadlock from background thread: now returns stub immediately
- Wall geometry at origin: added multi-attempt placement with `BRep3D`, AABB, Move/Rotate
- MCP server reconnect after bridge restart: `stop()` now closes active connections
