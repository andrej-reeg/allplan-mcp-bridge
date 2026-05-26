![CI](https://github.com/OWNER/allplan-mcp-bridge/actions/workflows/ci.yml/badge.svg)

# allplan-mcp-bridge

A production-grade MCP server that exposes Allplan's BIM API (geometry, attributes,
IFC import/export, and layer management) to MCP clients such as Claude Code and
Claude Desktop. The server runs as a normal Python process on Windows and communicates
with a PythonPart agent loaded inside Allplan over a Windows named pipe, enabling
Claude to create, query, and modify BIM elements while all operations remain in
Allplan's native undo history.
