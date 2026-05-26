# IPC Protocol Reference

## Transport

Windows named pipe (default) or loopback TCP (`127.0.0.1` only). Selected via
`ALLPLAN_MCP_IPC_TRANSPORT` env var. Named pipe name includes the Allplan PID to
support multiple instances.

## Framing

Every message is a **length-prefixed frame**:

```
┌───────────────────┬──────────────────────────────┐
│  4-byte big-endian│  UTF-8 JSON payload           │
│  uint32 length    │  (length bytes)               │
└───────────────────┴──────────────────────────────┘
```

- Maximum frame size: **16 MiB** (configurable via `ALLPLAN_MCP_MAX_FRAME_BYTES`).
- Frames exceeding the cap are rejected with a `frame_too_large` error frame
  **before** parsing the JSON payload.
- A truncated frame (connection closed mid-read) yields a sentinel error frame
  rather than raising an exception.

## Message shapes

### Request (server → agent)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "cmd": "create_wall",
  "args": { "start": [0,0,0], "end": [5000,0,0], "height_mm": 2800, "thickness_mm": 200 },
  "deadline_ms": 10000
}
```

### Response — success (agent → server)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "ok": true,
  "result": { "uuid": "abc123", "kind": "wall" },
  "elapsed_ms": 142
}
```

### Response — error (agent → server)

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "ok": false,
  "error": {
    "code": "AllplanApiError",
    "message": "Layer 'EXTERIOR' does not exist",
    "details": {}
  }
}
```

### Heartbeat (agent → server, unsolicited)

```json
{ "event": "heartbeat", "ts": 1716700000.123 }
```

Sent every 5 seconds when the agent is idle. The server tracks `last_heartbeat_at`
and considers the agent disconnected if no heartbeat arrives within 15 seconds.

## Error code taxonomy

| Code | Meaning |
|---|---|
| `InvalidArgs` | Pydantic validation failed on input |
| `Unauthorized` | IPC auth token mismatch |
| `NotFound` | Referenced element does not exist in the document |
| `AllplanApiError` | Allplan raised an exception in a handler |
| `Timeout` | `deadline_ms` elapsed before the command ran |
| `Cancelled` | Client cancelled the in-flight request |
| `AgentDisconnected` | Connection lost; in-flight request failed |
| `FrameTooLarge` | Incoming frame exceeds the 16 MiB cap |
| `Internal` | Unexpected server/agent error (queue full, panic, etc.) |

## TCP authentication handshake

When `ipc_transport = "tcp"`, the agent must send a hello frame as the **first**
message after connecting:

```json
{ "hello": "<token>" }
```

The token is read from a `0600`-permissioned file at `tcp_token_file`. Comparison
uses `hmac.compare_digest` to prevent timing attacks. The token is rotated on each
agent start.

If the hello frame is absent or the token is wrong, the connection is closed
immediately with no further response.
