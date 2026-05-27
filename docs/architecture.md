# Architecture — Allplan MCP Bridge

## Overview

Three processes cooperate to let Claude control Allplan:

```
┌─────────────────────────────────────────────────────────────────────┐
│  Claude Code / Claude Desktop                                       │
│  (MCP client)                                                       │
└─────────────────┬───────────────────────────────────────────────────┘
                  │  stdio  JSON-RPC  (MCP protocol)
                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  allplan_mcp_server                                                 │
│  (normal Python 3.12 process — runs outside Allplan)                │
│                                                                     │
│  FastMCP  →  tools/*  →  IpcClient  →  TcpTransport                │
└─────────────────┬───────────────────────────────────────────────────┘
                  │  TCP 127.0.0.1:49152  length-prefixed JSON
                  │  + HMAC token auth (token in ~/.allplan-mcp/token)
                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│  allplan_agent  (PythonPart — embedded inside Allplan's Python)     │
│                                                                     │
│  TcpListenerThread  →  CommandQueue  →  pump_once()                 │
│  (background)            (shared)       (main thread)               │
│                                              │                      │
│                                              ▼                      │
│                                    NemAll_Python_* APIs             │
│                                    → BIM document                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Process roles

### 1. MCP client (Claude Code / Claude Desktop)

- Sends MCP tool calls over stdio JSON-RPC.
- Never speaks directly to Allplan.
- Sees 20 tools; each returns JSON.

### 2. `allplan_mcp_server`

- A FastMCP server. Receives tool calls over stdio, translates them to IPC
  requests, and returns results.
- Runs on the host OS (or in WSL2 — TCP lets it cross the WSL2/Windows boundary).
- Auto-reconnects to the agent with exponential backoff (capped at 5 s).
- Tracks per-tool latency metrics (rolling window, p50/p95/p99).
- Exposes a `health` tool that reports agent connectivity and queue depth.

### 3. `allplan_agent`

- A PythonPart that Allplan loads at user activation.
- Runs inside Allplan's embedded Python (which may differ from the server's Python).
- Contains two threads:
  - **Listener thread** — accepts TCP connections, reads requests, enqueues
    `Command` objects, sends responses. Never calls `NemAll_Python_*`.
  - **Main thread** — driven by a QTimer (100 ms) and IFW callbacks. Drains the
    queue via `pump_once()`. Only this thread calls `NemAll_Python_*`.

---

## IPC protocol

See [`ipc-protocol.md`](ipc-protocol.md) for the full wire format.

Short version:
1. Agent generates a random token at startup, writes it to
   `~/.allplan-mcp/token` (Windows path, readable from WSL2 at
   `/mnt/c/Users/<user>/.allplan-mcp/token`).
2. On each TCP connection the agent sends `{"hello": "<token>"}` as the first
   frame; the client verifies it with `hmac.compare_digest` and sends
   `{"ack": true}`.
3. Subsequent frames are length-prefixed JSON requests and responses.
4. Agent sends `{"event": "heartbeat", "ts": ..., "queue_depth": N}` every 5 s.

---

## Data flow for `create_wall`

```
Claude                   MCP server              Allplan agent
  │                          │                       │
  │── create_wall(...) ──▶   │                       │
  │                          │── TCP: {id, cmd, args}▶│
  │                          │                       │ (listener thread enqueues)
  │                          │                       │ (QTimer fires: pump_once)
  │                          │                       │── build_wall_element()
  │                          │                       │── BaseElements.CreateElements()
  │                          │◀── TCP: {id, ok, result}│
  │◀── ElementRef(uuid) ──   │                       │
```

Total latency is dominated by the QTimer interval (100 ms). Typical round-trip: 100–300 ms.

---

## Threading model

See [`threading-model.md`](threading-model.md). The one law: **all
`NemAll_Python_*` calls must happen on Allplan's main thread**.

---

## Multi-instance note (v1 limitation)

v1 supports one Allplan instance. If you need to support multiple simultaneous
instances, the pipe name / port must include the Allplan PID, and the MCP server
needs a mechanism to select which instance to target. This is out of scope for v1.

---

## Scalability

The current 1-call-1-response model supports ~50 calls/sec on the TCP transport
(limited by the 100 ms QTimer drain interval and Allplan's COM serialisation). For
workflows needing higher throughput, a future `batch_execute(commands)` tool could
process multiple commands atomically inside one undo bracket.
