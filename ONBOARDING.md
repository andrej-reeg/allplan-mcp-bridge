# Allplan MCP Bridge — Colleague Setup Guide

Let Claude Desktop control Allplan 2026: create walls, slabs, columns, beams,
manage layers, set attributes, and import/export IFC — all by typing instructions
in Claude Desktop.

---

## Prerequisites

| | Requirement |
|---|---|
| Allplan | 2026 (installed, licensed) |
| Claude Desktop | Latest — [claude.ai/download](https://claude.ai/download) |
| Python | 3.12+ — [python.org/downloads](https://python.org/downloads) |
| uv | Run this once in PowerShell: `pip install uv` |

---

## Installation (5 steps, ~5 minutes)

### Step 1 — Get the code

Open **PowerShell** and run:

```powershell
cd "$env:USERPROFILE\Documents"
git clone https://github.com/andrej-reeg/allplan-mcp-bridge.git
cd allplan-mcp-bridge
uv sync
```

> No `git`? Download the ZIP from GitHub and extract it to
> `Documents\allplan-mcp-bridge`.

---

### Step 2 — Install the Allplan plugin

Still in that PowerShell window:

```powershell
python scripts\install_pythonpart.py
```

The script auto-detects your Allplan 2026 directories and copies the plugin files.
If it prints "Installed successfully" you are done. If it fails, see **Troubleshooting** below.

---

### Step 3 — Configure Claude Desktop

Open this file in Notepad (create it if it does not exist):

```
%APPDATA%\Claude\claude_desktop_config.json
```

Paste this content (replace `andrej` with your Windows username):

```json
{
  "mcpServers": {
    "allplan": {
      "command": "uv",
      "args": ["run", "python", "-m", "allplan_mcp_server"],
      "cwd": "C:\\Users\\andrej\\Documents\\allplan-mcp-bridge"
    }
  }
}
```

Save the file and **restart Claude Desktop**.

---

### Step 4 — Activate the bridge in Allplan

1. Launch Allplan 2026 and open any drawing/project.
2. In the **Library** panel, find **Allplan MCP Bridge** and double-click it.
3. A small palette appears showing:
   > Bridge running on `127.0.0.1:49152`

Leave that palette open while you work with Claude Desktop.

---

### Step 5 — Verify the connection

In Claude Desktop, start a new conversation and type:

> "What Allplan tools do you have available?"

Claude should list tools like `create_wall`, `export_ifc`, `health`, etc.

Then try a real test:

> "Create a 5000 mm wall from (0,0,0) to (5000,0,0), height 3000 mm, thickness 300 mm."

The wall appears in your open Allplan drawing.

---

## IMPORTANT: Keep Allplan in view while Claude works

Allplan processes Claude's commands on its **main thread**, driven by an internal
timer that fires roughly every 100–200 ms. While Claude is executing a sequence
of commands:

- **Keep the Allplan window visible** (do not minimize it).
- **Move your mouse over the Allplan window** occasionally if commands seem slow.
- Do not start another Allplan command (like drawing a wall manually) while the
  bridge is processing — Allplan's main thread can only do one thing at a time.

If a command times out, the bridge will tell Claude. Just ask Claude to retry.

---

## What you can ask Claude to do

```
Create a 6000 mm wall along the X axis at level 0, height 3200 mm, thickness 250 mm.

Create a rectangular room: four walls, 6000 × 4000 mm floor plan, height 2800 mm.

Move the wall with UUID <id> by 500 mm in the Y direction.

Export the model to IFC4 at C:\Projects\building.ifc.

Show me the attributes of element <uuid>.

Undo the last operation.
```

---

## Troubleshooting

**install_pythonpart.py can't find Allplan**

Pass the paths manually:
```powershell
python scripts\install_pythonpart.py `
  --scripts-dir "C:\Users\<you>\Documents\Nemetschek\Allplan\2026\Usr\Local\PythonPartsScripts" `
  --library-dir "C:\Users\<you>\Documents\Nemetschek\Allplan\2026\Usr\Local\Library"
```

**Claude Desktop shows "allplan: disconnected"**

1. Confirm the Allplan palette says "Bridge running on 127.0.0.1:49152".
2. Restart Claude Desktop after editing the config file.
3. Check the `cwd` path in `claude_desktop_config.json` matches where you cloned the repo.

**"timeout" when creating elements**

The command reached Allplan but the main thread was busy. Move the mouse over the
Allplan window and ask Claude to retry.

**Bridge palette shows an error on startup**

Open Allplan's Python console (View → Consoles → Python Console) and look for
error lines from `allplan_agent`. Common cause: Python version mismatch (Allplan
2026 uses Python 3.13 internally — this is fine, it runs in a separate process).

---

## Updating

When a new version is available:

```powershell
cd "$env:USERPROFILE\Documents\allplan-mcp-bridge"
git pull
uv sync
python scripts\install_pythonpart.py
```

Then restart Allplan and reactivate the Bridge palette.

---

## Questions?

Ask Andrej, or open an issue on GitHub.
