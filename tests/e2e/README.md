# End-to-End Tests — Allplan MCP Bridge

These tests require a real Allplan 2026 installation on Windows. They are skipped
in CI unless the `ALLPLAN_MCP_E2E=1` environment variable is set.

---

## Prerequisites

1. Allplan 2026 installed.
2. The MCP bridge PythonPart installed (run `scripts/install_pythonpart.py`).
3. `ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT` set to an accessible directory.
4. `ALLPLAN_MCP_E2E=1` in the environment.

---

## Manual E2E Checklist

Perform these steps in order. Check each box before proceeding.

### 1. PythonPart Activation

- [ ] Start Allplan 2026.
- [ ] Open a new or existing drawing.
- [ ] Activate **AllplanMcpBridge** from the toolbox / command bar.
- [ ] Palette appears showing **"Bridge running on `\\.\pipe\allplan-mcp-bridge`"**.
- [ ] Allplan Python console shows no errors from `allplan_agent`.

### 2. MCP Server Connection

- [ ] In a terminal, run: `uv run python -m allplan_mcp_server`
- [ ] Server log shows `"ipc.connected"` within a few seconds.
- [ ] No `"ipc.connect_failed"` or `"AuthError"` messages.

### 3. Tool: create_wall

- [ ] In Claude Code (or a test script): call `create_wall` with a 5000mm wall.
- [ ] Wall appears in the Allplan drawing viewport.
- [ ] Allplan undo history shows one new undo step.
- [ ] Press **Ctrl+Z** in Allplan — wall disappears. *(Undo works.)*
- [ ] Press **Ctrl+Y** — wall reappears. *(Redo works.)*

### 4. Tool: set_attributes

- [ ] Call `set_attributes` on the created wall (FireRating = "F30").
- [ ] Attribute appears in Allplan's element properties.
- [ ] Undo removes the attribute change without removing the wall.

### 5. Tool: export_ifc

- [ ] Call `export_ifc` with path inside `ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT`.
- [ ] IFC file appears on disk.
- [ ] IFC file opens correctly in a viewer (e.g. Solibri, BIMcollab Zoom).

### 6. Tool: import_ifc

- [ ] Call `import_ifc` with the file exported in step 5.
- [ ] Imported elements appear in the drawing.
- [ ] Allplan undo history shows one undo step for the full import.

### 7. Graceful Disconnect

- [ ] Kill the MCP server process (Ctrl+C).
- [ ] Allplan bridge palette updates to show **"Disconnected"** (or no crash).
- [ ] Allplan drawing is not corrupted.

### 8. Reconnect

- [ ] Restart the MCP server: `uv run python -m allplan_mcp_server`
- [ ] Server log shows `"ipc.reconnecting"` then `"ipc.connected"` within ~5 s.
- [ ] `create_wall` works again without restarting Allplan.

### 9. Mid-Operation Crash Safety

- [ ] During a long IFC export, kill the MCP server.
- [ ] Allplan drawing is not corrupted.
- [ ] Allplan undo history is consistent.

---

## Automated E2E Tests

The automated tests in `test_wall_creation.py` cover the happy path programmatically.
They require the same setup as the manual checklist.

Run with:

```powershell
$env:ALLPLAN_MCP_E2E = "1"
$env:ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT = "C:\Projects\Allplan"
uv run pytest tests/e2e/ -v
```
