# Contributing — Allplan MCP Bridge

## Development setup

```powershell
git clone https://github.com/andrej-reeg/allplan-mcp-bridge.git
cd allplan-mcp-bridge
uv sync --dev
uv run pre-commit install
```

Run the test suite:

```powershell
uv run pytest tests/unit tests/integration
uv run ruff check src tests
uv run mypy src
```

---

## Adding a new tool

Every new BIM operation must pass all 10 checks before merging.

### 10-box checklist

| # | Check | Where |
|---|---|---|
| 1 | Pydantic input model (in `models/`) | `src/allplan_mcp_server/models/` |
| 2 | Implementation runs on main thread only | review imports in `handlers/` |
| 3 | Wrapped in `safety.undo_bracket(cmd_name)` | `allplan_agent/handlers/` |
| 4 | Allplan exceptions caught → `AllplanApiError` | `allplan_agent/handlers/` |
| 5 | Returns `ElementRef`, never raw handle | handler return value |
| 6 | File paths validated via `security.validate_path` | any file-touching handler |
| 7 | Structured log: cmd name, ref(s), duration, undo state | `_log.info(...)` in handler |
| 8 | Unit test using fake API | `tests/unit/` |
| 9 | Integration test using fake agent | `tests/integration/` |
| 10 | E2E test `@pytest.mark.requires_allplan` | `tests/e2e/` |

### Step-by-step

**1. Add the Pydantic model** (`src/allplan_mcp_server/models/`):

```python
class SomethingSpec(BaseModel):
    """Specification for creating a something. Units: mm. Participates in undo."""
    point: Point3D
    size_mm: float = Field(gt=0, le=10_000_000.0)
    layer: str | None = None
```

**2. Add the agent handler** (`src/allplan_agent/handlers/`):

```python
@command("create_something")
def handle_create_something(args: dict[str, Any]) -> dict[str, Any]:
    spec = SomethingSpec.model_validate(args)
    if _USING_FAKE:
        ...  # fake path for tests
    # real Allplan path: queue the spec for main-thread insertion
    uuid_str = str(_uuid_mod.uuid4())
    queue_spec("something", spec)
    _log.info("geometry.create_something queued uuid=%s", uuid_str)
    return ElementRef(uuid=uuid_str, kind="something").model_dump()
```

**3. Add the MCP tool** (`src/allplan_mcp_server/tools/`):

```python
@mcp.tool()
async def create_something(point: Point3D, size_mm: float, layer: str | None = None) -> dict[str, Any]:
    """Create a something at the given point. Units: mm. Participates in undo."""
    spec = SomethingSpec(point=point, size_mm=size_mm, layer=layer)
    s = get_settings()
    return await get_client().call("create_something", spec.model_dump(mode="json"),
                                   timeout=s.request_timeout_seconds)
```

**4. Register the tool** in `src/allplan_mcp_server/tools/__init__.py`.

**5. Write tests** (unit + integration + e2e stub).

**6. Regenerate the tool catalog:**

```powershell
python scripts/generate_tool_catalog.py
```

**7. Update `CHANGELOG.md`** under a new version entry.

---

## Threading law

The #1 invariant — **all `NemAll_Python_*` calls must happen on Allplan's main thread**.
Read [`docs/threading-model.md`](docs/threading-model.md) before writing any handler code.

---

## Coding standards

- Type hints everywhere; `mypy --strict` must stay clean.
- No `print` — use `structlog` or the standard `logging` module (agent side).
- No bare `except:` — catch `Exception` at minimum, re-raise or convert to `AllplanApiError`.
- No `time.sleep` in the MCP server — use `anyio.sleep`.
- Unit tests must not touch the network, filesystem outside `tmp_path`, or Allplan.

---

## Commit convention

```
feat:  new feature
fix:   bug fix
test:  test-only change
docs:  documentation
chore: tooling, deps, CI
```

One phase per branch, PR per branch, squash-merge to `main`.
