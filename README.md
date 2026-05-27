![CI](https://github.com/andrej-reeg/allplan-mcp-bridge/actions/workflows/ci.yml/badge.svg)

# allplan-mcp-bridge

A production-grade MCP server that exposes Allplan's BIM API (geometry, attributes,
IFC import/export, and layer management) to MCP clients such as Claude Code and
Claude Desktop. Runs as a normal Python process that communicates with a PythonPart
agent embedded inside Allplan over local TCP, so Claude can create, query, and modify
BIM elements while every operation stays inside Allplan's native undo history.

---

## Quick start

### Prerequisites

| Component | Version |
|---|---|
| Allplan | 2026 (tested), likely works on 2025 / 2024-1 |
| OS | Windows 10 / 11 |
| Python (external) | 3.12+ |
| `uv` | `pip install uv` |
| Claude Code or Claude Desktop | Latest |

### 1 — Clone and install the MCP server

```powershell
git clone https://github.com/andrej-reeg/allplan-mcp-bridge.git
cd allplan-mcp-bridge
uv sync
```

### 2 — Install the Allplan PythonPart

```powershell
python scripts\install_pythonpart.py
```

Auto-detects the Allplan 2026 PythonParts directory. Pass `--scripts-dir` and
`--library-dir` explicitly if auto-detection fails.

### 3 — Activate the bridge in Allplan

1. Launch Allplan 2026 and open any project.
2. In the Library, find **Allplan MCP Bridge → AllplanMcpBridge** and activate it.
3. A palette should appear. The bridge is now listening on TCP port 49152.

### 4 — Start the MCP server

```powershell
uv run python -m allplan_mcp_server
```

You should see `{"event": "ipc.connected", ...}` in the log. If not, check that the
Allplan palette is visible and the bridge is active.

### 5 — Configure Claude Code (or Claude Desktop)

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "allplan": {
      "command": "uv",
      "args": ["run", "python", "-m", "allplan_mcp_server"],
      "cwd": "C:\\path\\to\\allplan-mcp-bridge"
    }
  }
}
```

Then ask Claude:

> "Create a 5 m wall at (0,0,0) to (5000,0,0), height 3000 mm, thickness 300 mm."

The wall should appear in Allplan, inside one undo bracket.

---

## Architecture

```
Claude Code / Desktop
     │  stdio JSON-RPC (MCP protocol)
     ▼
allplan_mcp_server          (this repo — normal Python 3.12 process)
     │  TCP 127.0.0.1:49152  length-prefixed JSON  + HMAC token auth
     ▼
allplan_agent               (PythonPart — runs INSIDE Allplan's embedded Python)
     │  thread-safe queue
     ▼
Allplan main thread → NemAll_Python_* API → BIM document
```

See [`docs/architecture.md`](docs/architecture.md) for the full picture and
[`docs/threading-model.md`](docs/threading-model.md) for the one law that must
never be broken.

---

## Configuration reference

All settings use the `ALLPLAN_MCP_` prefix. Set as environment variables or in a
`.env` file in the repository root.

| Variable | Default | Description |
|---|---|---|
| `ALLPLAN_MCP_IPC_TRANSPORT` | `tcp` | `tcp` or `named_pipe` |
| `ALLPLAN_MCP_TCP_HOST` | `127.0.0.1` | TCP host (loopback only) |
| `ALLPLAN_MCP_TCP_PORT` | `49152` | TCP port |
| `ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT` | auto-detected | Root path for IFC file allowlist |
| `ALLPLAN_MCP_REQUEST_TIMEOUT_SECONDS` | `10.0` | Timeout for standard operations |
| `ALLPLAN_MCP_LONG_OP_TIMEOUT_SECONDS` | `120.0` | Timeout for IFC import/export |
| `ALLPLAN_MCP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ALLPLAN_MCP_MAX_FRAME_BYTES` | `16777216` | IPC frame size cap (16 MiB) |
| `ALLPLAN_MCP_MAX_ARG_BYTES` | `1048576` | Per-tool argument size cap (1 MiB) |

---

## Available tools

See [`docs/tool-catalog.md`](docs/tool-catalog.md) for the full catalog with input
schemas and examples. Short summary:

| Category | Tools |
|---|---|
| Geometry | `create_wall`, `create_slab`, `create_column`, `create_beam`, `get_element`, `delete_element`, `move_element` |
| Document | `get_active_document_info`, `save_document`, `undo`, `redo` |
| Attributes | `get_attributes`, `set_attributes` |
| Layers | `list_layers`, `create_layer`, `set_layer_visibility`, `assign_layer` |
| IFC | `export_ifc`, `import_ifc` |
| Health | `health` |

---

## Supported Allplan versions

| Version | Status |
|---|---|
| Allplan 2026 | Tested, supported |
| Allplan 2025 | Should work — not formally tested |
| Allplan 2024-1 | Should work — not formally tested |
| Earlier | Not supported |

---

## Limitations (v1)

- **Single instance.** One Allplan + one MCP server. Multi-instance support is out of
  scope for v1; see `docs/architecture.md` for the design note.
- **Windows only.** Allplan is Windows-only. The MCP server can run in WSL2 and
  connect to Allplan over TCP.
- **Geometry only.** `create_slab`, `create_column`, `create_beam` create generic
  3-D solids (not architectural elements with material assignments). Architecture
  elements are planned for v2.
- **No live preview.** Elements are inserted when the bridge processes the command,
  not on mouse hover.
- **IFC size.** Exports > 1 GiB are hard-rejected. Exports > 100 MiB log a warning.
- **Main-thread serialisation.** All Allplan API calls run on the main thread. Heavy
  operations (large IFC export) will briefly freeze Allplan's UI.

---

## Troubleshooting

**`ipc.connect_failed` in MCP server logs**
- Confirm the Allplan palette is visible and shows "running".
- Check that the TCP port (default 49152) is not blocked.
- Check `~/.allplan-mcp/bridge.log` for errors from the agent.

**Wall/element created but in wrong position**
- Check `~/.allplan-mcp/debug.log` for `_wall: attempt N` lines — these show which
  geometry placement strategy succeeded.

**`PathNotAllowedError` on IFC export**
- The path is outside `ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT`.
- Either move the file or set the env var to a parent directory.

**Timeout errors on `get_active_document_info`**
- This call requires the Allplan main thread and returns `{main_thread_required: true}`
  when called from the background pump. Trigger a mouse event in Allplan (move the
  cursor into the drawing) to process the next tick.

---

## Development

```powershell
uv sync --dev
uv run pytest tests/unit tests/integration
uv run ruff check src tests
uv run mypy src
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for how to add a new tool.
