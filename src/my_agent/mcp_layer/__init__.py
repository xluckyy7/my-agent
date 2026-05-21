"""my_agent.mcp_layer — integration with the Model Context Protocol.

We use the official `mcp` Python SDK for protocol details (handshake,
JSON-RPC framing, notifications) and write a thin sync layer over its async
API. This is consistent with our existing approach of using openai SDK and
httpx — adapters, not frameworks.

The package is named `mcp_layer` (not `mcp`) to avoid shadowing the SDK
package name when reading source files.
"""
