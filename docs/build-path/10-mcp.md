---
step: 10
title: Connect through MCP
week: 7
capability: mcp
profile: profiles/steps/step-10.toml
time_box: 45 min
---
# Step 10: Connect through MCP

## Goal
The same tools served by two MCP servers, with no change to the graph.

## Concepts
MCP servers, tools and resources, stdio transport, request metadata for session identity, trust boundaries (write tools stay in the app), parity testing.

## Code added in this step
| File | Role |
|---|---|
| `mcp/campus_server.py` | campus read tools and the documents as resources |
| `mcp/public_server.py` | the four public-API tools |
| `mcp/client.py` | the MCP transport and a LangChain loader for the same tools |

## Run it
1. `python -m campus_copilot.cli step 10 --demo`
2. `python -m campus_copilot.cli mcp-serve campus`
3. `npx @modelcontextprotocol/inspector python -m campus_copilot.mcp.campus_server`

## What to observe
The scoreboard over MCP matches the in-process scoreboard. The Tools panel shows `transport: mcp` on every read call. The Inspector lists the campus tools and the handbook resources; no write tool appears there.

## Checkpoint
`python -m campus_copilot.cli step 10 --check` runs `tests/steps/test_step_10.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E10 (MCP servers).
