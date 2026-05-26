# Threat Model — Allplan MCP Bridge

## Scope

Single-user, single-machine deployment. One Allplan instance, one MCP server process, one MCP client (Claude Code or Claude Desktop). All communication is local.

Out of scope: multi-user, cloud hosting, network exposure, multiple simultaneous Allplan instances.

---

## Trust Boundaries

```
[Claude Code / MCP client]
        │  stdio JSON-RPC (local process)
        ▼
[FastMCP server process]       ← TRUST BOUNDARY A
        │  local IPC (named pipe or loopback TCP)
        ▼
[Allplan agent (PythonPart)]   ← TRUST BOUNDARY B
        │  direct API calls (same process)
        ▼
[Allplan main thread / NemAll_Python_*]
```

**Boundary A** — between the MCP client and the FastMCP server. Mitigated by: stdio transport (no network socket), same-user process ownership.

**Boundary B** — between the FastMCP server and the Allplan agent. Mitigated by: named pipe ACL (Windows, current-user SID only) or loopback TCP with token auth (hmac.compare_digest, token rotated on every server start, token file 0600).

---

## Assets

| Asset | Risk if compromised |
|---|---|
| Active Allplan document | Data corruption, geometry destruction |
| IFC files on disk | Data exfiltration, overwrite |
| Allplan workspace files | As above |
| Allplan undo history | Silent corruption if undo brackets skipped |

---

## Threat Catalogue

### T1 — Path traversal to files outside workspace

**Attack:** Caller passes `../../etc/passwd` or a symlink pointing outside the workspace root.

**Mitigations:**
- `security.validate_path()` called on every path argument before use.
- Uses `Path.resolve()` which follows all symlinks before comparison.
- Rejects: relative paths, paths resolving outside workspace_root, UNC paths (`\\server\share`, `//server/share`).
- Applied to: IFC import, IFC export, any future file-touching tool.

**Residual risk:** None on supported platforms. Windows case-folding is handled by `resolve()` on the OS level.

---

### T2 — Unauthorized IPC connection

**Named pipe (Windows, primary):**
- Pipe created with ACL restricting to current user SID.
- Even if another local process guesses the pipe name, the OS rejects the connection.

**Loopback TCP (fallback):**
- Server binds to `127.0.0.1` only; `0.0.0.0` is explicitly rejected in `TcpTransport.__init__`.
- First frame from server is `{"hello": "<token>"}`. Client verifies with `hmac.compare_digest` to prevent timing attacks.
- Token is 32 random bytes (hex-encoded), rotated on every server start.
- Token file written with `0600` permissions; other users cannot read it.
- A wrong or absent token causes `AuthError`; no diagnostic info is leaked.

---

### T3 — Oversized / malformed IPC frames

**Attack:** Pathological input exhausts memory or triggers parser bugs.

**Mitigations:**
- 4-byte length prefix read first; frames > 16 MiB (configurable via `max_frame_bytes`) rejected *before* JSON parsing.
- Per-tool argument size cap: JSON-encoded args > 1 MiB (configurable via `max_arg_bytes`) rejected in `IpcClient.call()` before sending.
- IFC export hard limit: 1 GiB (configurable via `ifc_export_max_bytes`); warning logged at 100 MiB.
- Command queue bounded at 256; overflow returns `Internal` error without crashing the agent.
- Frame rejection yields a sentinel error dict; the reader loop continues (or stops cleanly for truncated frames).

---

### T4 — Injection via user-supplied inputs

**Attack:** Inputs that trigger `eval`, `exec`, or dynamic attribute lookups.

**Mitigations:**
- All inputs pass through Pydantic models with strict typing.
- No `eval`, `exec`, `__import__`, or `getattr(obj, user_string)` anywhere in the codebase.
- Attribute names in `set_attributes` are validated against the Pydantic `AttributeSpec` model. Handler receives parsed `AttributeSpec` objects, not raw strings.
- JSON parsing uses the standard library `json.loads`; no custom deserialiser.

---

### T5 — Information leakage in error messages

**Attack:** Error responses reveal absolute paths, stack traces, or internal state that help an attacker enumerate the filesystem or understand the system.

**Mitigations:**
- `IpcError.__str__` returns `"<code>: <message> [correlation_id: <uuid>]"` — no paths or stack traces.
- Server logs the full error (including details and correlation_id) at ERROR level; the client only sees the sanitised string.
- `security.validate_path` error messages use `path.name` only (no full path).
- `logging.py` path redactor strips absolute paths from all log fields outside the workspace root when `log_level != DEBUG`.
- IFC handler logs use `safe_path.name` only.

---

### T6 — Attribute value exfiltration via logs

**Attack:** Attribute values (potentially containing PII, cost data, or confidential model data) appear in logs and are forwarded to a log aggregator.

**Mitigations:**
- `set_attributes` handler logs only attribute count (`attributes.set uuid=... count=N`), never values.
- `get_attributes` handler does not log the returned values.
- No tool-level logging of attribute values at INFO level.

---

### T7 — Allplan document corruption via unchecked exceptions

**Attack:** An exception mid-operation leaves the document in a partial state (e.g., wall created but attributes not set).

**Mitigations:**
- Every handler that mutates the document is wrapped in `safety.undo_bracket()`.
- On exception: rollback is called before re-raising.
- `pump_once()` isolates each command; one failing command never kills the drain loop.
- Create operations followed by a re-read to verify key properties (Phase 5 handler checklist item 8).

---

### T8 — Allplan API called from wrong thread

**Attack / bug:** Any code path that calls `NemAll_Python_*` from the listener thread causes Allplan to crash or produce silent corruption.

**Mitigations:**
- See `docs/threading-model.md` — this is treated as a hard invariant, not a mitigation.
- The listener module is statically forbidden from importing `_allplan` shim.
- CI grep enforces: `grep -r "from.*_allplan import" src/allplan_agent/listener.py` must return empty.

---

## Security Controls Summary

| Control | Where | What it guards |
|---|---|---|
| `security.validate_path()` | server + agent | T1 |
| Named pipe ACL / TCP token | transport layer | T2 |
| Frame size cap (16 MiB) | `ipc/framing.py` | T3 |
| Arg size cap (1 MiB) | `ipc/client.py` | T3 |
| IFC export size limit (1 GiB) | `allplan_agent/handlers/ifc.py` | T3 |
| Queue size cap (256) | `allplan_agent/command_queue.py` | T3 |
| Pydantic models on all inputs | models/ | T4 |
| `IpcError` correlation_id + sanitised str | `ipc/client.py` | T5 |
| Path redactor in structlog | `logging.py` | T5 |
| Attribute handler log discipline | handlers/attributes.py | T6 |
| `safety.undo_bracket()` | every mutating handler | T7 |
| Thread-safety invariant | threading model | T8 |

---

## Non-mitigations (out of scope for v1)

- Physical access to the machine (full-disk encryption is the OS's responsibility).
- Malicious Allplan plugins installed by the user (they run in the same process with full API access regardless).
- Denial-of-service from a user with shell access to the machine (they can kill the process directly).
