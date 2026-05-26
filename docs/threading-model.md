# Threading Model — Allplan MCP Bridge

## The One Law

**All Allplan API calls (`NemAll_Python_*`) must be made on Allplan's main thread.**

This is not a preference or a performance guideline. Allplan's COM/internal architecture is single-threaded; calling its APIs from any other thread results in either silent data corruption, access violations, or undefined behaviour that is invisible until something goes wrong in the drawing.

---

## System Topology

```
┌─────────────────────────────────────────────────────────┐
│  Allplan process                                         │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Main thread (Qt event loop + Allplan tick)      │   │
│  │                                                  │   │
│  │   QTimer (100 ms)                                │   │
│  │       └──▶ pump_once(queue)                      │   │
│  │                 └──▶ handler(args)               │   │
│  │                           └──▶ NemAll_Python_*   │   │
│  └──────────────────────────────────────────────────┘   │
│                         ▲  queue.enqueue()               │
│  ┌──────────────────────┴───────────────────────────┐   │
│  │  Listener thread (daemon)                        │   │
│  │   - Accepts IPC connections                      │   │
│  │   - Reads frames from socket/pipe                │   │
│  │   - Enqueues Commands                            │   │
│  │   - Awaits Future.result()                       │   │
│  │   - Sends response frames                        │   │
│  └──────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

---

## Thread Roles

### Main thread

- Runs Allplan's Qt event loop.
- Owns a 100 ms `QTimer` callback that calls `pump_once(queue)`.
- `pump_once()` drains up to 8 commands per tick and calls each handler synchronously.
- Handlers call `NemAll_Python_*` and return a result dict.
- Results are set into `concurrent.futures.Future` objects for pick-up by the listener thread.

**Invariants:**
- Only `pump_once()` calls handlers; nothing else does.
- No asyncio on the main thread; Allplan's embedded Python does not run an asyncio event loop.
- No `time.sleep()` calls; the timer re-fires automatically.

### Listener thread

- A single background daemon thread.
- Accepts connections on a Windows named pipe (or loopback TCP on non-Windows).
- For each incoming request frame: creates a `Command` + `Future`, enqueues the command, then blocks on `Future.result(timeout=...)`.
- Never reads from the queue; never calls handlers; never imports `NemAll_Python_*`.

**Invariants:**
- Never imports from `allplan_agent/handlers/_allplan.py` (enforced by `grep` in CI).
- Never calls `pump_once()`.
- Blocking on `Future.result()` is intentional — it ensures back-pressure when the queue is full.

---

## Shared State

The **command queue** (`CommandQueue`, wrapping `queue.Queue`) is the **only** shared mutable state between the two threads.

| Object | Thread | Mutation |
|---|---|---|
| `CommandQueue._q` | Listener writes (enqueue), main reads (drain) | Atomic via `queue.Queue` |
| `Command.future` | Listener reads (`.result()`), main writes (`.set_result()`/`.set_exception()`) | `concurrent.futures.Future` is thread-safe |
| Everything else | One thread only | N/A |

There are no locks other than those inside `queue.Queue` and `concurrent.futures.Future`. This is intentional: fewer synchronisation primitives mean fewer deadlock opportunities.

---

## Deadline and Timeout Flow

```
Client sends request with deadline_ms=10000
       │
       ▼
Listener thread
  command.deadline_at = time.monotonic() + 10.0
  queue.enqueue(command)
  future.result(timeout=11.0)   # slightly wider than deadline
       │
       ▼
Main thread (pump_once)
  if time.monotonic() > command.deadline_at:
      future.set_exception(TimeoutError(...))
      continue
  result = handler(command.args)
  future.set_result(result)
       │
       ▼
Listener thread
  → sends response or Timeout error frame
```

If `pump_once()` is called late (e.g. Qt timer was delayed by a heavy operation), commands may expire in the queue. That is correct and safe: the listener sees `TimeoutError` and sends a `Timeout` error frame back to the client.

---

## What Happens When Things Go Wrong

| Scenario | Behaviour |
|---|---|
| Handler raises an exception | `future.set_exception(exc)`; next command proceeds normally. `pump_once` never propagates. |
| Queue full (256 items) | `QueueFullError`; listener sends `Internal` error frame immediately, does not enqueue. |
| Listener thread crashes | Daemon thread dies silently. Main thread is unaffected. Reconnection logic in the FastMCP server handles reconnect. |
| Main thread blocked (e.g. modal dialog) | `QTimer` callbacks paused; commands expire in queue with `Timeout`. Client retries. |
| `stop_bridge()` called | Timer stopped first; listener thread stopped; queue drained by the shutdown caller. |

---

## CI Enforcement

The following grep in CI prevents accidental main-thread law violations:

```bash
# Must return no output — listener must not import _allplan
grep -r "from.*_allplan import\|import.*_allplan" \
    src/allplan_agent/listener.py \
    src/allplan_agent/command_queue.py
```

This runs as part of every CI push (see `.github/workflows/ci.yml`).

---

## Adding a New Handler

1. Create the handler function in `src/allplan_agent/handlers/<category>.py`.
2. Decorate with `@command("cmd_name")`.
3. Verify: the handler imports everything it needs from `._allplan` (the shim), never from a thread-spawning module.
4. Verify: the handler is synchronous (no `async def`, no `await`).
5. Verify: no `time.sleep()`, no `threading.Thread()`, no `asyncio` calls inside the handler.
6. See `CONTRIBUTING.md` for the full 10-item checklist.
