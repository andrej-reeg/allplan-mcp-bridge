# Installation Guide — Allplan MCP Bridge

## Prerequisites

| Component | Requirement |
|---|---|
| Allplan | 2026 (tested), may work on 2025 / 2024-1 |
| OS | Windows 10 / 11 (Allplan is Windows-only) |
| Python (external) | 3.12+ (for the FastMCP server — NOT Allplan's embedded Python) |
| uv | Latest (`pip install uv`) |
| Claude Code or Claude Desktop | Latest |

---

## Step 1 — Clone and install the MCP server

```powershell
git clone https://github.com/your-org/allplan-mcp-bridge.git
cd allplan-mcp-bridge
uv sync
```

---

## Step 2 — Install the Allplan PythonPart

Run the install script from the repository root. It will auto-detect the Allplan PythonParts directory:

```powershell
python scripts\install_pythonpart.py
```

If auto-detection fails (e.g. custom Allplan install path), pass both directories explicitly:

```powershell
python scripts\install_pythonpart.py `
  --scripts-dir "C:\ProgramData\Nemetschek\Allplan\2026\PythonParts" `
  --library-dir "C:\Users\<user>\Documents\Nemetschek\Allplan\2026\Usr\Local\PythonParts"
```

The script copies:
- `src/allplan_agent/` → `<PythonParts>/allplan_agent/`
- `src/allplan_mcp_server/models/` → `<PythonParts>/allplan_mcp_server/models/` (vendored)
- `bridge_config.json` → `<PythonParts>/allplan_agent/bridge_config.json`
- `AllplanMcpBridge.pyp` → `<PythonParts>/AllplanMcpBridge.pyp`

The script is **idempotent** — re-running it only updates files that have changed.

---

## Step 3 — Start Allplan and activate the PythonPart

1. Launch Allplan 2026.
2. Open any project/drawing.
3. In the **Script PythonParts** toolbox (or search the command bar), find and activate **AllplanMcpBridge**.
4. A palette should appear showing "Bridge running on `127.0.0.1:49152`".

If the palette shows an error, check the Allplan Python console for log output from `allplan_agent`.

---

## Step 4 — Start the MCP server

In a separate terminal (outside Allplan):

```powershell
uv run python -m allplan_mcp_server
```

TCP is the default transport. No environment variables required for a standard install.

You should see in the logs:
```json
{"event": "ipc.connected", "level": "info", ...}
```

If you see `ipc.connect_failed`, check that the Allplan PythonPart is active and the bridge palette is visible.

---

## Step 5 — Configure Claude Code

Add to your Claude Code MCP configuration (`~/.claude/claude_desktop_config.json` or equivalent):

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

`ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT` is auto-detected from your Allplan installation (looks for `Documents\Nemetschek\Allplan\<version>\Usr\Local`). Set it explicitly if IFC import/export paths are rejected:

```json
"env": { "ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT": "C:\\Projects\\Allplan" }
```

---

## Step 6 — Verify the connection

In Claude Code, ask:

> "List the available Allplan tools."

You should see tools like `create_wall`, `export_ifc`, `get_attributes`, etc.

Then test end-to-end:

> "Create a 5000mm wall at coordinates (0,0,0) to (5000,0,0) with height 3000mm and thickness 300mm."

The wall should appear in the active Allplan drawing. Check Allplan's undo history — the wall should be inside one undo bracket.

---

## Configuration Reference

All settings use the `ALLPLAN_MCP_` prefix. They can be set as environment variables or in a `.env` file in the repository root.

| Variable | Default | Description |
|---|---|---|
| `ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT` | *(auto-detected)* | Root path for IFC file allowlist |
| `ALLPLAN_MCP_IPC_TRANSPORT` | `tcp` | `tcp` or `named_pipe` |
| `ALLPLAN_MCP_PIPE_NAME` | `\\.\pipe\allplan-mcp-bridge` | Named pipe path (if transport=named_pipe) |
| `ALLPLAN_MCP_TCP_HOST` | `127.0.0.1` | TCP host (loopback only) |
| `ALLPLAN_MCP_TCP_PORT` | `49152` | TCP port |
| `ALLPLAN_MCP_REQUEST_TIMEOUT_SECONDS` | `10.0` | Timeout for standard operations |
| `ALLPLAN_MCP_LONG_OP_TIMEOUT_SECONDS` | `120.0` | Timeout for IFC import/export |
| `ALLPLAN_MCP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ALLPLAN_MCP_MAX_ARG_BYTES` | `1048576` | Per-tool argument size cap (1 MiB) |

---

## Updating

To update the MCP server:

```powershell
git pull
uv sync
```

To update the Allplan agent (re-run install script — it's idempotent):

```powershell
python scripts\install_pythonpart.py
```

Then restart Allplan and reactivate the PythonPart.

---

## Uninstalling

1. Deactivate the PythonPart in Allplan (click Stop Bridge or close the palette).
2. Delete the installed files:
   ```powershell
   Remove-Item -Recurse "C:\ProgramData\Nemetschek\Allplan\2026\PythonParts\allplan_agent"
   Remove-Item "C:\ProgramData\Nemetschek\Allplan\2026\PythonParts\AllplanMcpBridge.pyp"
   ```
3. Remove the MCP server entry from Claude Code config.

---

## Troubleshooting

**"Bridge not started" / palette shows error**
- Check Allplan's Python console for errors from `allplan_agent`.
- Verify `bridge_config.json` exists in the agent directory.
- Try deactivating and reactivating the PythonPart.

**`ipc.connect_failed` in MCP server logs**
- Confirm the Allplan PythonPart palette is visible and shows "running".
- Verify `ALLPLAN_MCP_TCP_PORT` (default 49152) is not blocked by a firewall.
- Check `bridge_config.json` has `"force_tcp": true` — regenerate with `scripts\install_pythonpart.py`.

**Wall created but attributes not set**
- This indicates a partial failure. Check Allplan undo history — the wall should have been rolled back if attribute setting failed.
- Enable `DEBUG` log level and look for `pump_once.error` entries with `correlation_id`.

**`PathNotAllowedError` on IFC export**
- The export path is outside `ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT`.
- Set the env var to include your target directory.
