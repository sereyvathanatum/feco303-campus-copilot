---
id: E10
title: MCP servers
week: 7
time_box: 45 min
profiles: [e10_mcp]
---
# E10: MCP servers

## Goal
Serve the tools over MCP and prove that nothing else changes.

## Steps
1. Start MCP Inspector on the campus server: `npx @modelcontextprotocol/inspector python -m campus_copilot.mcp.campus_server` and list its tools and resources.
2. Run `python -m campus_copilot.cli --profile e10_mcp demo` and compare with `python -m campus_copilot.cli demo`.
3. Run `python -m pytest tests/test_mcp.py -q` (the parity test).
4. Add one new read tool to `tools/campus.py`, add its name to `CAMPUS_TOOLS` in `mcp/campus_server.py`, and call it from the Inspector without touching the graph.

## Evidence
| Check | In-process | Over MCP |
|---|---|---|
| Demo scoreboard | | |
| Tools listed | | |
| Parity test | | |

## Questions
1. Why are write tools not exposed over MCP?
2. How does the server learn the session account without a tool argument?

## Stretch
Load the same tools as LangChain tools with `campus_copilot.mcp.client.langchain_tools` and list their names.

Reference results: `experiments/_reference/E10.md`.
