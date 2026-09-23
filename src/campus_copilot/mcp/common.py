"""Shared MCP server plumbing (docs/implementation-plan.md §8.7).

Both servers publish tools straight from the registry specs, so the MCP tool list
matches the native and JSON-protocol schemas exactly. The session account travels
as MCP request metadata (`_meta.account_id`), never as a tool argument.

The installed SDK is the v1 line (`mcp==1.30.0`); the low-level `Server` class is
used because it accepts the registry's JSON Schemas as they are.
"""

from __future__ import annotations

import json
import os

from .. import config

PROFILE_ENV = "COPILOT_PROFILE_JSON"


def settings_from_env():
    """The parent process passes its exact profile (with overrides) as JSON; otherwise the named profile loads."""
    raw = os.environ.get(PROFILE_ENV)
    if raw:
        data = json.loads(raw)
        profile = config.Profile(name=data.get("__name__", "mcp"), data={k: v for k, v in data.items() if k != "__name__"})
        return config.get_settings(profile)
    return config.get_settings()


def account_from(server) -> str:
    try:
        meta = server.request_context.meta
    except LookupError:
        meta = None
    account = None
    if meta is not None:
        account = getattr(meta, "account_id", None) or (getattr(meta, "model_extra", None) or {}).get("account_id")
    return account or os.environ.get("COPILOT_MCP_ACCOUNT") or "A0001"


def build_server(name: str, tool_names: list[str], with_resources: bool = False):
    from mcp import types
    from mcp.server.lowlevel import Server

    from ..tools.registry import ToolContext, registry

    settings = settings_from_env()
    reg = registry()
    specs = [reg.get(n) for n in tool_names]
    server = Server(name)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name=s.name, description=s.description, inputSchema=s.mcp_schema()["inputSchema"])
                for s in specs]

    @server.call_tool(validate_input=False)  # the registry validates, so both transports report errors alike
    async def call_tool(tool: str, arguments: dict) -> dict:
        if tool not in tool_names:
            return {"ok": False, "tool": tool, "args": arguments, "error": f"tool '{tool}' is not served here",
                    "summary": f"{tool} is not available over MCP."}
        ctx = ToolContext.create(settings, account_from(server))
        return reg.run(tool, arguments, ctx)

    if with_resources:
        from ..ingest import store as kb

        @server.list_resources()
        async def list_resources() -> list[types.Resource]:
            conn = kb.connect()
            rows = conn.execute("SELECT source_id, title, format FROM documents WHERE status = 'ingested' ORDER BY source_id")
            return [types.Resource(uri=f"campus://documents/{r['source_id']}", name=r["source_id"],
                                   description=r["title"], mimeType="text/plain") for r in rows]

        @server.read_resource()
        async def read_resource(uri) -> str:
            source_id = str(uri).rsplit("/", 1)[-1]
            conn = kb.connect()
            rows = conn.execute("SELECT page, section, text FROM chunks WHERE source_id = ? ORDER BY position",
                                (source_id,)).fetchall()
            if not rows:
                raise ValueError(f"unknown document {source_id}")
            return "\n\n".join((f"[p.{r['page']}] " if r["page"] else f"[§ {r['section']}] ") + r["text"] for r in rows)

    return server


def serve(server) -> None:
    import anyio
    from mcp.server.stdio import stdio_server

    async def main():
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(main)
