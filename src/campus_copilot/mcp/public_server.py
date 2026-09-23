"""MCP server for the four public-API tools: a second server, to show a multi-server setup.

Run: `python -m campus_copilot.mcp.public_server` (stdio) or `python -m campus_copilot.cli mcp-serve public`.
"""

from __future__ import annotations

from .common import build_server, serve

PUBLIC_TOOLS = ["campus_weather", "convert_currency", "search_books", "concept_summary"]


def server():
    return build_server("campus-copilot-public", PUBLIC_TOOLS)


if __name__ == "__main__":
    serve(server())
