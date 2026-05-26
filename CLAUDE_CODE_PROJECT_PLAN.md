# Allplan MCP Bridge — Claude Code Implementation Plan

> **Audience:** Claude Code, executing this plan in an empty repository.
> **Goal:** A production-grade MCP server that exposes Allplan's BIM API (geometry, attributes, IFC, layers) to MCP clients (Claude Code, Claude Desktop) over stdio, with a thread-safe IPC bridge into Allplan's embedded Python.
> **Non-goals:** GUI plugins for Allplan, multi-user collaboration, cloud hosting. Single-user, local-machine, single Allplan instance.

---

## 0. Operating instructions for Claude Code

Before writing any code:

1. Read this file end-to-end.
2. Read `pyproject.toml` and existing source once it exists; do not assume.
3. Work **phase by phase**. Do not skip ahead. Each phase has an *exit criterion* — verify it before moving on.
4. After each phase, run the tests for that phase and commit. Use conventional commit messages (`feat:`, `fix:`, `test:`, `chore:`, `docs:`).
5. When a decision is ambiguous, prefer the option that is (a) safer, (b) easier to test, (c) easier to revert.
6. If you encounter an Allplan API uncertainty (parameter shape, return type, version differences), **stop and ask the user** — do not guess and proceed. Allplan API mistakes are silent and can corrupt drawings.
7. Never call Allplan APIs from any thread other than the main thread. This is the single most important rule. Every code path must be reviewed against it.

---

## 1. Architecture recap

Three processes / boundaries:

```
Claude Code  ──stdio JSON-RPC──▶  FastMCP server  ──local IPC──▶  Allplan PythonPart agent
   (client)                       (external proc)                  (in-process, embedded)
                                                                          │
                                                                          ▼
                                                                   Allplan main thread
                                                                   → NemAll_Python_*
```

- **FastMCP server** runs in a normal Python 3.12 venv on the user's machine. Exposes tools to Claude Code over stdio.
- **Allplan agent** is a PythonPart loaded by Allplan. Owns a listener thread (accepts IPC), a thread-safe queue, and a main-thread drainer that calls the Allplan API.
- **IPC choice:** Windows named pipe by default (no port allocation, OS-level ACL, survives firewall changes). Fall back to loopback TCP + token only if named-pipe perms become a problem on a given machine.

---

## 2. Repository layout

Create this layout in phase 1. Do not create files outside this tree without explicit reason.

```
allplan-mcp/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
├── src/
│   ├── allplan_mcp_server/         # The FastMCP process (runs in normal Python)
│   │   ├── __init__.py
│   │   ├── __main__.py             # Entry point: python -m allplan_mcp_server
│   │   ├── server.py               # FastMCP instance + tool registration
│   │   ├── config.py               # Pydantic Settings, env vars, defaults
│   │   ├── ipc/
│   │   │   ├── __init__.py
│   │   │   ├── transport.py        # Abstract Transport interface
│   │   │   ├── named_pipe.py       # Windows named pipe client
│   │   │   ├── tcp.py              # Loopback TCP fallback
│   │   │   ├── framing.py          # length-prefixed JSON codec
│   │   │   └── client.py           # Request/response correlator, timeouts
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── _base.py            # Shared helpers, error mapping
│   │   │   ├── geometry.py         # walls, slabs, columns, beams, generic 3D
│   │   │   ├── attributes.py       # Allplan attributes get/set
│   │   │   ├── layers.py           # layer create/list/assign
│   │   │   ├── ifc.py              # IFC import/export
│   │   │   └── document.py         # active doc info, save, undo
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── geometry.py         # Pydantic: Point3D, Vector3D, WallSpec, etc.
│   │   │   ├── attributes.py
│   │   │   ├── layers.py
│   │   │   └── references.py       # ElementRef, WallRef, LayerRef
│   │   ├── security.py             # Path allowlist, IFC sandbox checks
│   │   └── logging.py              # structlog setup, redaction
│   │
│   └── allplan_agent/              # The PythonPart side (runs INSIDE Allplan)
│       ├── __init__.py
│       ├── pythonpart_entry.py     # PythonPart's required entry hooks
│       ├── listener.py             # Background thread, accepts IPC
│       ├── command_queue.py        # thread-safe queue + Future correlation
│       ├── main_loop.py            # Idle-tick drainer
│       ├── dispatcher.py           # cmd_name → handler function
│       ├── handlers/
│       │   ├── __init__.py
│       │   ├── geometry.py         # All NemAll_Python_BasisElements calls
│       │   ├── attributes.py
│       │   ├── layers.py
│       │   ├── ifc.py
│       │   └── document.py
│       └── safety.py               # Allplan-side guardrails (undo bracketing)
│
├── tests/
│   ├── unit/
│   │   ├── test_framing.py
│   │   ├── test_models.py
│   │   ├── test_command_queue.py
│   │   ├── test_dispatcher.py
│   │   ├── test_security.py
│   │   └── test_ipc_client.py      # Uses fake transport
│   ├── integration/
│   │   ├── conftest.py             # Spins up a fake Allplan agent (no Allplan)
│   │   ├── test_tool_roundtrip.py
│   │   ├── test_timeout.py
│   │   ├── test_concurrent.py
│   │   └── test_reconnect.py
│   ├── e2e/                        # Requires real Allplan; gated by env var
│   │   ├── README.md
│   │   └── test_wall_creation.py
│   └── fakes/
│       ├── fake_agent.py           # In-memory agent honoring the IPC protocol
│       └── fake_allplan_api.py     # Stand-in for NemAll_Python_* during unit tests
│
├── docs/
│   ├── architecture.md             # The diagrams from the previous step
│   ├── ipc-protocol.md             # Wire format, message types, error codes
│   ├── tool-catalog.md             # Generated list of MCP tools
│   ├── installation.md             # Allplan-side install steps
│   └── threading-model.md          # The one law: API calls on main thread only
│
└── scripts/
    ├── install_pythonpart.py       # Copies allplan_agent/ into Allplan's PythonParts dir
    └── dev_run.py                  # Local dev loop runner
```

---

## 3. Phase-by-phase plan

Each phase has: **deliverables**, **exit criteria**, **what to test**. Do not advance until exit criteria are met.

### Phase 1 — Foundation (no Allplan needed)

**Deliverables:**
- `pyproject.toml` using `uv` or `hatch`. Python 3.12. Dependencies pinned:
  - `fastmcp>=2.0` (verify latest)
  - `pydantic>=2.7`
  - `pydantic-settings`
  - `structlog`
  - `anyio`
  - Dev: `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `mypy`, `pre-commit`
- `.gitignore` (Python, IDE, Allplan working files: `*.ndw`, `*.nds`, `.allplan_cache/`)
- `.github/workflows/ci.yml`: ruff, mypy, pytest unit + integration on push.
- `README.md` with status badge and one-paragraph project description.
- `src/allplan_mcp_server/logging.py`: structlog config with JSON output, automatic redaction of file paths outside the project root, log level from env.
- `src/allplan_mcp_server/config.py`: `Settings` class with `ipc_transport` (`"named_pipe" | "tcp"`), `pipe_name`, `tcp_host`, `tcp_port`, `tcp_token`, `request_timeout_seconds` (default 10), `long_op_timeout_seconds` (default 120), `allplan_workspace_root` (path allowlist root), `log_level`.
- Pre-commit hook running ruff + mypy.

**Exit criteria:**
- `uv run pytest` passes (no tests yet, exit 5 is acceptable; or add one smoke test).
- `uv run ruff check src tests` clean.
- `uv run mypy src` clean.
- CI green on a placeholder PR.

---

### Phase 2 — IPC protocol & framing (no Allplan needed)

This is the foundation everything else rests on. Get it right.

**The wire protocol (document in `docs/ipc-protocol.md`):**

- Framing: 4-byte big-endian length prefix, then UTF-8 JSON payload. Max frame size: 16 MiB (configurable). Frames exceeding the cap are rejected with `frame_too_large` *before* parsing.
- Request shape:
  ```json
  {"id": "uuid4-string", "cmd": "create_wall", "args": {...}, "deadline_ms": 10000}
  ```
- Response shape (success):
  ```json
  {"id": "...", "ok": true, "result": {...}, "elapsed_ms": 142}
  ```
- Response shape (error):
  ```json
  {"id": "...", "ok": false, "error": {"code": "AllplanApiError", "message": "...", "details": {...}}}
  ```
- Server → agent only sends requests. Agent → server only sends responses (no server-initiated push in v1).
- Heartbeat: agent sends `{"event": "heartbeat", "ts": ...}` every 5s when idle. Server tracks last-seen.

**Error code taxonomy (closed set):**
`InvalidArgs`, `Unauthorized`, `NotFound`, `AllplanApiError`, `Timeout`, `Cancelled`, `AgentDisconnected`, `FrameTooLarge`, `Internal`.

**Deliverables:**
- `ipc/framing.py`: `encode(obj) -> bytes`, `decode_stream(reader) -> AsyncIterator[dict]`. Strict cap, strict UTF-8, never raises on malformed input — yields a sentinel error frame instead.
- `ipc/transport.py`: `class Transport(Protocol)` with `connect()`, `send(bytes)`, `recv() -> bytes`, `close()`.
- `ipc/named_pipe.py`: Windows named pipe transport using `pywin32` or `ctypes`. ACL set so only the current user can connect. Pipe name includes a per-session random suffix written to a known file the server reads.
- `ipc/tcp.py`: Loopback-only TCP. Binds to `127.0.0.1`. Auth: first frame must be `{"hello": "<token>"}`; token read from a 0600-permissioned file in the user profile. **Never** bind to `0.0.0.0`.
- `ipc/client.py`: `IpcClient` class. Maintains one connection, a `dict[uuid, Future]` for in-flight requests, a reader task that demuxes responses. Public API: `async call(cmd: str, args: dict, timeout: float) -> dict`. Auto-reconnect with exponential backoff (capped at 5s). On disconnect, in-flight futures resolve with `AgentDisconnected`.

**What to test (`tests/unit/test_framing.py`, `test_ipc_client.py`):**
- Round-trip encode/decode of all message shapes.
- Truncated frame → no crash, error frame yielded.
- Oversized frame → rejected without parsing.
- Concurrent calls with interleaved responses correlate correctly by id.
- Timeout fires and future resolves even if response arrives late (late response is dropped).
- Reconnect: kill the fake transport, verify backoff and that pending calls fail cleanly.

**Exit criteria:** All unit tests pass. Coverage on `ipc/` ≥ 90%.

---

### Phase 3 — Agent skeleton & fake Allplan API

Build the agent's threading model *without* Allplan. We'll inject Allplan calls later.

**Deliverables:**

- `tests/fakes/fake_allplan_api.py`: Module that mimics `NemAll_Python_BasisElements` and friends with deterministic outputs. The agent's handlers import the *real* Allplan modules at runtime via a thin shim:
  ```python
  # In allplan_agent/handlers/_allplan.py
  try:
      import NemAll_Python_BasisElements as AllplanBaseElements
      import NemAll_Python_Geometry as AllplanGeo
      ...
  except ImportError:
      from tests.fakes import fake_allplan_api as AllplanBaseElements
      ...  # plus a noisy log line
  ```
  This shim is the *only* place the import fallback lives. All handlers import via it.

- `allplan_agent/command_queue.py`: A `CommandQueue` wrapping `queue.Queue`. Each enqueued item is a `Command(id, cmd_name, args, future, deadline_at)`. The queue is bounded (default 256); enqueue raises `QueueFull` mapped to `Internal` over IPC.

- `allplan_agent/main_loop.py`: `pump_once()` drains up to N (default 8) commands per tick. Each command:
  1. Check `deadline_at`; if past, set `Timeout` and skip.
  2. Look up handler via dispatcher.
  3. Run inside an Allplan undo bracket (begin/commit/rollback on exception).
  4. Set future result or exception.
  5. Log structured event with command id, name, duration, ok/err.

  Exceptions never propagate out of `pump_once`. One bad command must not kill the loop.

- `allplan_agent/listener.py`: Background thread. Owns the IPC server side (named pipe accept loop or TCP accept). For each incoming request: build a `Future`, enqueue, await result, send response. Multiple concurrent in-flight requests are allowed — they all queue.

- `allplan_agent/dispatcher.py`: Registry mapping `cmd_name -> callable`. Handlers register via decorator `@command("create_wall")`. Unknown command → `InvalidArgs`.

- `allplan_agent/safety.py`:
  - Argument validation via Pydantic models (re-use server-side models — share the `models/` package).
  - Path allowlist enforcement for any handler that reads/writes files (IFC import/export). Rejects paths outside `allplan_workspace_root`.
  - Undo-bracket context manager.

**Threading model — non-negotiable rules:**

1. The listener thread **never** imports `NemAll_Python_*`. It only does I/O and enqueues.
2. `pump_once` is called exclusively from the main thread (driven by a PythonPart timer/idle hook).
3. Handler functions are synchronous and assume they're on the main thread. They never spawn threads. They never call `asyncio`.
4. Futures used for cross-thread result delivery are `concurrent.futures.Future`, not `asyncio.Future`.
5. The queue is the *only* shared mutable state between the two threads.

**What to test:**
- 1000 concurrent enqueues from N listener-simulating threads → all drained in FIFO-per-producer order, no lost commands.
- Handler raising → future gets exception, loop survives, next command runs.
- Deadline-exceeded command never enters the handler.
- Queue full → caller gets `Internal` error, agent stays healthy.
- Property test (Hypothesis): random sequences of enqueue/drain preserve invariants.

**Exit criteria:** All threading tests pass under `pytest -p no:randomly --count=20` (run each test 20× to flush races). Use `pytest-repeat` or a small wrapper.

---

### Phase 4 — Models & validation

Pydantic models live in `src/allplan_mcp_server/models/` and are imported by *both* the server and the agent (the agent runs in Allplan's embedded Python, so we'll vendor or symlink the models package at install time — see Phase 8).

**Deliverables:**

- `models/geometry.py`:
  - `Point3D(x: float, y: float, z: float)` — units: millimetres. Document this.
  - `Vector3D` likewise.
  - `WallSpec(start: Point3D, end: Point3D, height_mm: float, thickness_mm: float, layer: str | None = None, axis_offset_mm: float = 0)`
  - `SlabSpec`, `ColumnSpec`, `BeamSpec`, `GenericSolidSpec` (closed polyhedra from vertices+faces).
  - Validators: positive dimensions, non-degenerate geometry (start != end, thickness > 0), max extents (configurable cap — refuse a 10km wall).
- `models/attributes.py`: `AttributeValue` union (`str | int | float | bool`), `AttributeSpec(name: str, value: AttributeValue)`. Allplan attribute numeric IDs handled via a name-to-id mapping module loaded at agent start.
- `models/layers.py`: `LayerSpec(name: str, parent: str | None, visible: bool, locked: bool)`.
- `models/references.py`: `ElementRef(uuid: str, kind: Literal["wall","slab",...])`. All handlers return these, never raw Allplan handles.
- `models/ifc.py`: `IfcExportSpec(path: Path, schema: Literal["IFC2X3","IFC4"], elements: list[ElementRef] | None)`. Path must pass the allowlist.

**What to test:**
- Validation rejects: negative thickness, zero-length wall, NaN coordinates, paths outside workspace, IFC schemas not in the literal.
- Round-trip JSON serialization stable.

**Exit criteria:** 100% branch coverage on validators.

---

### Phase 5 — Handlers (the Allplan-touching code)

This phase has the most uncertainty because Allplan's API has version differences. **For each handler, write the test first using the fake API, then implement against the real API.**

**Handler categories and the Allplan modules they touch (verify against installed Allplan version):**

- **Geometry** — `NemAll_Python_BasisElements`, `NemAll_Python_Geometry`, `NemAll_Python_AllplanSettings`
  - `create_wall`, `create_slab`, `create_column`, `create_beam`, `create_generic_solid`
  - `get_element(ref)` — returns geometry + attributes
  - `delete_element(ref)`
  - `move_element(ref, vector)`, `rotate_element(ref, axis, angle_rad)`

- **Attributes** — `NemAll_Python_BaseElements` attribute API
  - `get_attributes(ref) -> dict[str, AttributeValue]`
  - `set_attributes(ref, attrs: dict)`
  - `list_attribute_definitions() -> list[AttributeDefinition]`

- **Layers** — `NemAll_Python_AllplanSettings.LayerService`
  - `list_layers()`, `create_layer(spec)`, `set_layer_visibility`, `assign_layer(ref, layer_name)`

- **IFC** — Allplan's IFC import/export
  - `export_ifc(spec)` — must validate path against allowlist
  - `import_ifc(path)` — must validate path against allowlist; returns list of `ElementRef`
  - Always wrap in undo bracket so failures don't half-import.

- **Document** — `NemAll_Python_IFW_Input`, `NemAll_Python_BaseElements`
  - `get_active_document_info()` — name, path, units
  - `save_document()`
  - `undo()`, `redo()`

**Per-handler checklist (Claude Code must apply this for every handler):**

1. Pydantic input model and output model defined.
2. Implementation runs entirely on the main thread (review imports).
3. Wrapped in undo bracket via `safety.undo_bracket(name=cmd_name)`.
4. All exceptions from Allplan caught and re-raised as `AllplanApiError` with the original message preserved.
5. Element handles never leak — convert to `ElementRef` before returning.
6. File paths validated against `security.path_allowlist`.
7. Structured log: command name, input hash, output ref(s), duration, undo state.
8. Unit test using fake API.
9. Integration test using fake agent.
10. E2E test marked `@pytest.mark.requires_allplan` (skipped in CI).

**Exit criteria:** Every handler has all 10 boxes ticked.

---

### Phase 6 — MCP tool surface

This is the FastMCP side that Claude Code (the user's) actually sees.

**Deliverables:**

- `src/allplan_mcp_server/server.py`:
  ```python
  from fastmcp import FastMCP
  mcp = FastMCP("allplan-bridge")
  # Tools registered via tools/*.py modules
  ```

- For each handler in Phase 5, expose a corresponding tool:
  ```python
  @mcp.tool
  async def create_wall(spec: WallSpec) -> ElementRef:
      """Create a wall in the active Allplan document.

      Units: millimetres. The wall is created on the active layer
      unless `spec.layer` is provided.
      """
      return await ipc.call("create_wall", spec.model_dump(),
                            timeout=settings.request_timeout_seconds)
  ```

- **Docstring discipline:** Every tool docstring must state:
  - One-sentence purpose.
  - Units used (mm, radians, etc.).
  - Side effects on the Allplan document (creates, mutates, reads).
  - Whether it participates in undo (yes for all v1 tools — they're wrapped agent-side).

- **Long-running operations** (IFC import/export of large models): use `long_op_timeout_seconds`. Do not split into async polling in v1 — the synchronous tool-call model is simpler and Claude tolerates 60-120s waits fine.

- `src/allplan_mcp_server/__main__.py`:
  ```python
  if __name__ == "__main__":
      configure_logging()
      ipc.start()  # connects to agent, retries until success
      mcp.run()    # stdio transport
  ```

**What to test (integration tests in `tests/integration/`):**
- Spin up `fake_agent.py` (an in-process agent that honors the IPC protocol with fake Allplan handlers).
- Run the real `FastMCP` server in-process (`mcp.run()` has a test mode; otherwise use FastMCP's `Client`).
- For each tool: call it, verify the agent received the right command, verify the response is the right Pydantic shape.
- Concurrency: 16 concurrent `create_wall` calls — all complete, all unique refs.
- Timeout: agent sleeps longer than `request_timeout_seconds` → tool returns `Timeout` error.
- Disconnect: kill agent mid-call → tool returns `AgentDisconnected`; reconnect; next call works.

**Exit criteria:** All integration tests green. Coverage on `tools/` ≥ 85%.

---

### Phase 7 — Security hardening

Security review checklist. Each item must be a real code-level control, not just a comment.

**Path safety:**
- `security.py::validate_path(path)` rejects: non-absolute paths, paths outside `allplan_workspace_root`, paths containing `..` (even resolved ones if they escape), symlinks pointing outside the root.
- Applied to: IFC import/export, any future tool that reads/writes files.

**IPC auth:**
- Named pipe: ACL restricts to current user SID. Verify on accept (`GetNamedPipeClientProcessId` + token check).
- TCP: token comparison uses `hmac.compare_digest`. Token rotated on each server start. Token file 0600.

**Resource limits:**
- IPC frame cap (16 MiB).
- Queue size cap (256).
- Per-tool argument size cap (configurable, default 1 MiB after JSON encode) — rejects pathological inputs.
- IFC export size warning at 100 MiB, hard fail at 1 GiB (configurable).

**Input sanitization:**
- All inputs go through Pydantic — no `eval`, no `exec`, no dynamic attribute lookups based on input.
- Attribute names checked against the loaded Allplan attribute definition list before being passed to the API.

**Logging redaction:**
- File paths in log output are stripped to filename only unless `log_level=DEBUG`.
- No log of attribute *values* (might contain PII in real models) at INFO level — only names.

**Error message hygiene:**
- Errors returned to the MCP client never include full stack traces or absolute paths.
- Original details are logged server-side with a correlation id; the client gets `{"code": ..., "message": ..., "correlation_id": "..."}` and can quote the id when asking the user to check logs.

**What to test:**
- Path traversal: `../../etc/passwd`, symlinks, UNC paths, mixed case on Windows.
- Token: wrong token → connection rejected, no info leak.
- Oversized frame → rejected, agent still healthy.
- Pathological inputs (deeply nested JSON, huge strings) → rejected at framing or model layer.

**Exit criteria:** A dedicated `tests/unit/test_security.py` covering all the above passes. Document the threat model in `docs/threat-model.md`.

---

### Phase 8 — Allplan-side installation & runtime

The agent has to actually run inside Allplan. This phase is where most surprises live.

**Allplan PythonPart constraints (verify against installed version):**

- PythonParts live in a specific directory tree. The agent must register as a PythonPart, not just any Python script.
- The PythonPart's `create_element` (or equivalent entry callback) is called on the main thread when the user activates it. This is our hook to start the listener thread and the main-thread drain timer.
- Allplan's embedded Python version may differ from the server's. Pin a Python version supported by both, or have a separate `requirements-agent.txt`.

**Deliverables:**

- `allplan_agent/pythonpart_entry.py`: The PythonPart entry hooks. On activation:
  1. Start the listener thread (idempotent — second activation does nothing).
  2. Register a recurring main-thread callback that calls `pump_once()`. Use Allplan's own timer mechanism if available; otherwise a `QTimer` since Allplan is Qt-based.
  3. Show a small palette indicating "Bridge running on `<pipe_name>`".
  4. Provide a "Stop bridge" button that joins threads cleanly.

- `scripts/install_pythonpart.py`:
  - Detects the Allplan version and PythonParts directory.
  - Copies `src/allplan_agent/` and a vendored copy of `src/allplan_mcp_server/models/` into the right location.
  - Writes a `bridge_config.json` next to it (pipe name, token file location).
  - Does NOT install pip packages into Allplan's embedded Python without the user's confirmation.

- `docs/installation.md`: Step-by-step install, including how to start Allplan, activate the PythonPart, then start the MCP server.

- `docs/threading-model.md`: A standalone document explaining the one law and how every code path respects it. Required reading for anyone modifying the agent.

**What to test:**
- The install script is idempotent.
- E2E test (manual checklist in `tests/e2e/README.md`):
  1. Start Allplan, activate PythonPart, confirm palette appears.
  2. Start MCP server, see "connected to agent" in logs.
  3. Use Claude Code to call `create_wall` — wall appears in Allplan.
  4. Undo in Allplan — wall disappears.
  5. Kill MCP server — agent stays healthy, shows "disconnected" in palette.
  6. Restart server — reconnects automatically.

**Exit criteria:** Manual E2E checklist passes on a clean Windows machine with the supported Allplan version.

---

### Phase 9 — Observability & scaling

For a single-user single-machine setup, "scaling" mostly means: doesn't degrade, doesn't leak, surfaces problems clearly.

**Deliverables:**

- **Metrics** (stdout/JSON, no Prometheus dep in v1):
  - Per-tool: call count, error count, p50/p95/p99 latency (rolling window of 1000 samples).
  - Queue depth (sampled every 5s).
  - Reconnect count.
- **Tracing:** Every request gets a `correlation_id` propagated through server log → IPC frame → agent log. Makes post-mortem trivial.
- **Health endpoint:** A `health` MCP tool returns `{server_ok, agent_connected, queue_depth, last_heartbeat_age_ms, version}`.
- **Graceful shutdown:** SIGINT on the server flushes pending requests up to a 5s deadline, then closes IPC.

**Scale considerations to document (not necessarily implement):**
- Multiple Allplan instances: out of scope for v1. Document that the pipe name includes the Allplan PID and only one bridge runs per Allplan instance.
- Batching: the current 1-call-1-response model is fine up to ~50 calls/sec on a single named pipe. If a workflow needs more, add a `batch_execute(commands)` tool later — agent processes the batch atomically inside one undo bracket.

**Exit criteria:** `health` tool returns useful info, correlation ids visible in both logs, graceful shutdown verified.

---

### Phase 10 — Documentation & handoff

**Deliverables:**

- `README.md`: Quick start (install agent, start server, configure Claude Code), supported Allplan versions, limitations.
- `docs/tool-catalog.md`: Auto-generated from FastMCP introspection (write a small script in `scripts/`).
- `docs/architecture.md`: The diagrams from this conversation.
- `docs/ipc-protocol.md`: Wire format reference.
- `docs/threat-model.md`: From phase 7.
- `docs/threading-model.md`: From phase 8.
- `CHANGELOG.md`: Started.
- `CONTRIBUTING.md`: How to add a new tool (the 10-box checklist from phase 5).

**Exit criteria:** A second engineer (or future Claude Code instance) can stand up the project from `README.md` alone.

---

## 4. Cross-cutting standards (apply to all phases)

**Coding:**
- Type hints everywhere. `mypy --strict` on `src/`.
- No `print` — `structlog` only.
- No bare `except:` — always catch a specific exception or `Exception` with re-raise.
- No `time.sleep` in production code — use `anyio.sleep` or event-driven waits.

**Testing:**
- Unit tests don't touch the network, the filesystem outside `tmp_path`, or Allplan.
- Integration tests use the fake agent, run in-process.
- E2E tests require Allplan and are gated by `ALLPLAN_MCP_E2E=1`.
- Every bug fix gets a regression test first.

**Git:**
- Conventional commits.
- One phase per branch, PR per branch, squash-merge.
- No commits straight to `main`.

**CI must run:**
- ruff
- mypy --strict
- pytest unit + integration with coverage report
- A "thread safety" job that runs the threading tests with `--count=20`

---

## 5. Risk register (Claude Code should re-read before each phase)

| Risk | Mitigation |
|---|---|
| Calling Allplan API from listener thread | Static check: agent listener module forbidden from importing `_allplan` shim; CI grep enforces. |
| Allplan API version differences | All API calls behind handlers; handlers tested against a fake; real-Allplan tests are E2E and version-tagged. |
| Pipe/socket name collision between Allplan instances | Pipe name includes Allplan PID. |
| Long IFC export blocks the main thread (UI freeze) | Document the trade-off; v1 accepts it. v2 might offload via Allplan's own background job API if it exists. |
| Pydantic model drift between server and agent | Single source of truth in `src/allplan_mcp_server/models/`; install script vendors it into the agent location with a hash check. |
| FastMCP version churn | Pin `fastmcp` to a tested minor version; bump deliberately with a smoke test. |
| User-supplied IFC paths escaping workspace | `security.validate_path` plus the OS-level user ACL on the pipe means even a compromised server can't access another user's files. |
| Silent Allplan failures (API returns success but does nothing) | Where possible, every create/mutate handler re-reads the element afterward and verifies key properties. Log a warning if they don't match. |

---

## 6. What "done" looks like

The project is v1-complete when:

1. All ten phases pass their exit criteria.
2. CI is green on `main`.
3. A user can: install the PythonPart, start Allplan, start the MCP server, configure Claude Code, and successfully ask Claude to "create a 5m wall on layer EXTERIOR with attribute FireRating=F30 and export the whole model to IFC4 at C:\\Projects\\demo.ifc" — and the wall appears, the attribute is set, the IFC file is created. All inside Allplan's undo history.
4. Killing the server mid-operation never corrupts the Allplan document.
5. The tool catalog (`docs/tool-catalog.md`) lists every BIM operation in scope, each with input/output schemas and one example.

---

## 7. First message Claude Code should send the user

After reading this plan, before writing any code, Claude Code should reply with:

> I've read the plan. Confirm the Allplan version you're targeting (e.g. Allplan 2024-1, 2026), and the path to the PythonParts directory on this machine. I'll start with Phase 1 once confirmed.
