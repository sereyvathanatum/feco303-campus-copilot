"""MCP transport (`tools.transport = mcp`): the graph code does not change.

`MCPTransport` launches both servers over stdio once, keeps the sessions open on a
background event loop, and offers the same synchronous `call(name, args, account)`
as the in-process transport. The session account travels as request metadata.

`langchain_tools()` shows the other route: loading the same MCP tools as LangChain
tools through `langchain-mcp-adapters` (used in E10).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from contextlib import AsyncExitStack

from .. import config
from .common import PROFILE_ENV

SERVERS = {"campus": "campus_copilot.mcp.campus_server", "public": "campus_copilot.mcp.public_server"}
CALL_TIMEOUT = 60.0


def server_env(settings) -> dict:
    env = dict(os.environ)
    env[PROFILE_ENV] = json.dumps({"__name__": settings.profile.name, **settings.profile.data}, default=str)
    env["COPILOT_RUNS_DIR"] = str(config.runs_dir())
    env.setdefault("PYTHONIOENCODING", "utf-8")
    src = str(config.REPO_ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return env


def server_params(settings, name: str):
    from mcp import StdioServerParameters

    return StdioServerParameters(command=sys.executable, args=["-m", SERVERS[name]], env=server_env(settings))


class MCPTransport:
    name = "mcp"

    def __init__(self, rt, servers: tuple[str, ...] = ("campus", "public")) -> None:
        self.rt = rt
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="mcp-client", daemon=True)
        self.thread.start()
        self.stack: AsyncExitStack | None = None
        self.sessions: dict[str, object] = {}
        self.tools: dict[str, dict] = {}
        self._run(self._start(servers), timeout=CALL_TIMEOUT)

    def _run(self, coro, timeout: float = CALL_TIMEOUT):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    async def _start(self, servers) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client

        self.stack = AsyncExitStack()
        for name in servers:
            read, write = await self.stack.enter_async_context(stdio_client(server_params(self.rt.settings, name)))
            session = await self.stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            for tool in listed.tools:
                self.sessions[tool.name] = session
                self.tools[tool.name] = {"name": tool.name, "description": tool.description,
                                         "inputSchema": tool.inputSchema, "server": name}

    def call(self, name: str, args: dict, account_id: str) -> dict:
        session = self.sessions.get(name)
        if session is None:
            return {"ok": False, "tool": name, "args": args, "error": f"tool '{name}' is not served over MCP",
                    "summary": f"{name} is not available over MCP."}
        result = self._run(session.call_tool(name, args, meta={"account_id": account_id}))
        if getattr(result, "structuredContent", None):
            data = dict(result.structuredContent)
        else:
            text = "".join(getattr(block, "text", "") for block in result.content)
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = {"ok": not result.isError, "tool": name, "args": args, "summary": text}
        data["transport"] = "mcp"
        return data

    def list_resources(self) -> list[dict]:
        session = self.sessions.get("search_handbook")
        listed = self._run(session.list_resources())
        return [{"uri": str(r.uri), "name": r.name, "description": r.description} for r in listed.resources]

    def read_resource(self, uri: str) -> str:
        session = self.sessions.get("search_handbook")
        result = self._run(session.read_resource(uri))
        return "".join(getattr(c, "text", "") for c in result.contents)

    def close(self) -> None:
        if self.stack is not None:
            try:
                self._run(self.stack.aclose(), timeout=15)
            except Exception:
                pass
            self.stack = None
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)


async def langchain_tools(settings):
    """Load both servers' tools as LangChain tools (langchain-mcp-adapters)."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    env = server_env(settings)
    client = MultiServerMCPClient({name: {"command": sys.executable, "args": ["-m", module], "env": env,
                                          "transport": "stdio"} for name, module in SERVERS.items()})
    return await client.get_tools()
