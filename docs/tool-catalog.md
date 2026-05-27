# Tool Catalog — Allplan MCP Bridge

All 20 MCP tools exposed by `allplan_mcp_server`. All lengths are in **millimetres**
unless stated. All create/mutate tools participate in Allplan's **undo history**.

---

## Geometry

### `create_wall`

Create a wall element in the active document.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `start` | `{x, y, z}` | ✓ | Start point (mm) |
| `end` | `{x, y, z}` | ✓ | End point (mm) |
| `height_mm` | float | ✓ | Wall height > 0 |
| `thickness_mm` | float | ✓ | Wall thickness > 0 |
| `layer` | string | — | Layer name (uses active layer if omitted) |
| `axis_offset_mm` | float | — | Axis offset from wall centre (default 0) |

**Returns:** `{"uuid": "...", "kind": "wall"}`

**Example:**
```
create_wall(start={x:0,y:0,z:0}, end={x:5000,y:0,z:0}, height_mm=3000, thickness_mm=300)
```

---

### `create_slab`

Create a slab element from a polygon outline.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `outline` | list of `{x,y,z}` | ✓ | Polygon corners, ≥ 3 points |
| `thickness_mm` | float | ✓ | Slab thickness > 0 |
| `layer` | string | — | Layer name |

**Returns:** `{"uuid": "...", "kind": "slab"}`

---

### `create_column`

Create a rectangular column element.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `base` | `{x, y, z}` | ✓ | Base centre point |
| `height_mm` | float | ✓ | Column height |
| `width_mm` | float | ✓ | Column width (X) |
| `depth_mm` | float | ✓ | Column depth (Y) |
| `layer` | string | — | Layer name |

**Returns:** `{"uuid": "...", "kind": "column"}`

---

### `create_beam`

Create a beam element between two points.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `start` | `{x, y, z}` | ✓ | Start point |
| `end` | `{x, y, z}` | ✓ | End point |
| `width_mm` | float | ✓ | Cross-section width |
| `height_mm` | float | ✓ | Cross-section height |
| `layer` | string | — | Layer name |

**Returns:** `{"uuid": "...", "kind": "beam"}`

---

### `get_element`

Retrieve an element by UUID.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `uuid` | string | ✓ | Element UUID (from a create call) |
| `kind` | string | ✓ | `wall` / `slab` / `column` / `beam` / `solid` / `unknown` |

**Returns:** `{"uuid": "...", "kind": "..."}` — raises if not found.

---

### `delete_element`

Delete an element by UUID. Participates in undo.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `uuid` | string | ✓ | Element UUID |
| `kind` | string | ✓ | Element kind |

**Returns:** `{"deleted": true, "uuid": "..."}`

---

### `move_element`

Translate an element by a vector. Participates in undo.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `uuid` | string | ✓ | Element UUID |
| `kind` | string | ✓ | Element kind |
| `dx` | float | ✓ | X translation (mm) |
| `dy` | float | ✓ | Y translation (mm) |
| `dz` | float | ✓ | Z translation (mm) |

**Returns:** `{"uuid": "...", "kind": "..."}`

---

## Document

### `get_active_document_info`

Return metadata about the active Allplan document. Read-only.

**Returns:** `{"drawing_file": N, "layout": N, ...}` — exact fields depend on
Allplan version. May return `{"main_thread_required": true}` if called before
a main-thread tick; retry after moving the mouse in Allplan.

---

### `save_document`

Save the active document to disk.

**Returns:** `{"saved": true}`

---

### `undo`

Undo the last operation.

**Returns:** `{"ok": true}`

---

### `redo`

Redo the last undone operation.

**Returns:** `{"ok": true}`

---

## Attributes

### `get_attributes`

Return all scalar attributes of an element. Read-only.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `uuid` | string | ✓ | Element UUID |
| `kind` | string | ✓ | Element kind |

**Returns:** `{"attributes": [{"name": "FireRating", "value": "F30"}, ...]}`

---

### `set_attributes`

Set one or more attributes on an element. Participates in undo.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `uuid` | string | ✓ | Element UUID |
| `kind` | string | ✓ | Element kind |
| `attributes` | list | ✓ | `[{"name": "...", "value": ...}, ...]` |

**Returns:** `{"updated": N, "uuid": "..."}`

**Example:**
```
set_attributes(uuid="...", kind="wall", attributes=[{"name": "FireRating", "value": "F30"}])
```

---

## Layers

### `list_layers`

Return all layers in the active document. Read-only.

**Returns:** `{"layers": [{"name": "EXTERIOR", "visible": true, "locked": false}, ...]}`

---

### `create_layer`

Create a new layer.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | string | ✓ | Layer name |
| `parent` | string | — | Parent layer name |
| `visible` | bool | — | Default `true` |
| `locked` | bool | — | Default `false` |

**Returns:** `{"name": "...", "visible": true, "locked": false}`

---

### `set_layer_visibility`

Show or hide a layer by name.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `name` | string | ✓ | Layer name |
| `visible` | bool | ✓ | `true` to show, `false` to hide |

**Returns:** `{"name": "...", "visible": true/false}`

---

### `assign_layer`

Assign an element to a layer. Participates in undo.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `uuid` | string | ✓ | Element UUID |
| `kind` | string | ✓ | Element kind |
| `layer` | string | ✓ | Target layer name |

**Returns:** `{"uuid": "...", "layer": "..."}`

---

## IFC

### `export_ifc`

Export the model (or selected elements) to an IFC file. Uses
`long_op_timeout_seconds` (default 120 s). Path must be absolute and inside
`ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT`.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | ✓ | Absolute path ending in `.ifc` |
| `schema_version` | string | — | `IFC4` (default) or `IFC2X3` |
| `element_uuids` | list[string] | — | Subset to export; `null` = full model |

**Returns:** `{"path": "...", "size_bytes": N, "elements": N}`

**Example:**
```
export_ifc(path="C:\\Projects\\demo.ifc", schema_version="IFC4")
```

---

### `import_ifc`

Import an IFC file into the active document. Uses `long_op_timeout_seconds`.
Path must be inside `ALLPLAN_MCP_ALLPLAN_WORKSPACE_ROOT`. The entire import is
wrapped in one undo bracket.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `path` | string | ✓ | Absolute path ending in `.ifc` |

**Returns:** `{"imported": N, "elements": [{"uuid": "...", "kind": "..."}]}`

---

## Health

### `health`

Return server and agent health status. Read-only.

**Returns:**
```json
{
  "server_ok": true,
  "agent_connected": true,
  "last_heartbeat_age_ms": 1200,
  "queue_depth": 0,
  "reconnect_count": 0,
  "version": "0.1.0",
  "tools": {
    "create_wall": {"calls": 12, "errors": 0, "p50_ms": 180, "p95_ms": 310, "p99_ms": 450}
  }
}
```

---

## Error codes

All errors follow the shape `{"code": "...", "message": "...", "correlation_id": "..."}`.

| Code | Meaning |
|---|---|
| `InvalidArgs` | Argument validation failed (Pydantic or size cap) |
| `Unauthorized` | Token auth failed |
| `NotFound` | Element UUID not found |
| `AllplanApiError` | Allplan API call raised an exception |
| `Timeout` | No response within `request_timeout_seconds` |
| `Cancelled` | Operation was cancelled |
| `AgentDisconnected` | Bridge not running or connection lost |
| `FrameTooLarge` | IPC frame exceeded 16 MiB cap |
| `Internal` | Unexpected server-side error; see server log with `correlation_id` |

---

*To regenerate this file run: `python scripts/generate_tool_catalog.py`*
