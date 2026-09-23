# verify@build findings

Items marked `verify@build` in `docs/implementation-plan.md`, as found when the
repository was built (September 2026, Windows, Python 3.14.6).

| Item | Plan assumption | Found at build | Effect |
|---|---|---|---|
| Python | 3.10 and 3.12 | only 3.14.6 on the build machine; CI covers 3.10 and 3.12 | code avoids syntax newer than 3.10 |
| `langchain-nvidia-ai-endpoints` | pin at build | `1.4.3` installs beside `langchain-core==1.6.3` | pinned |
| `langgraph-checkpoint-sqlite` | pin at build | `3.1.1` | pinned |
| `mcp` | v2 line, `MCPServer` class | latest release is `1.30.0`; the server class is `FastMCP` (`mcp.server.fastmcp`) | servers use `FastMCP`; a v2 upgrade renames one import |
| LangChain MCP adapter | `langchain.mcp.MCPAdapter` or `langchain-mcp-adapters` | `langchain-mcp-adapters==0.3.2` | client uses `MultiServerMCPClient` |
| `sqlite-vec` | pin at build | `0.1.9`; loads on CPython 3.14 for Windows | pinned |
| SQLite FTS5 | may be missing | present in CPython 3.14 for Windows | lexical search uses FTS5 |
| `gradio` | pin at build | `6.28.0` | pinned |
| `numpy` | pin | wheels differ per Python version | range `>=1.26,<3` keeps 3.10 installable |
