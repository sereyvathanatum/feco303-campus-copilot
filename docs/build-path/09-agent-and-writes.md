---
step: 9
title: Agent loop and safe writes
week: 7
capability: agent, writes
profile: profiles/steps/step-09.toml
time_box: 60 min
---
# Step 9: Agent loop and safe writes

## Goal
A chatbot that combines several sources in a bounded loop and changes data only after an explicit confirmation.

## Concepts
The ReAct loop, stopping rules (call limit, repeat detector), three agent modes, a risk gate before writes, human-in-the-loop confirmation with `interrupt()`, memory slots ('Book it.').

## Code added in this step
| File | Role |
|---|---|
| `graph/agent.py` | the bounded loop in `native`, `json`, and `laya_dispatch` modes |
| `graph/nodes.py` | `agent_reason`, `agent_act`, `risk_gate`, `confirm` |
| `tools/campus.py` | `book_room`, `place_hold`, `add_event` with rule checks |

## Run it
1. `python -m campus_copilot.cli step 9 --chat`
2. `python -m campus_copilot.cli step 9 --demo`

## What to observe
Turn 8 calls the free-room search and the forecast, then answers. Turn 9 ('Book it.') resolves 'it' from memory and stops with Confirm / Cancel; Cancel leaves the database unchanged. With `--set agent.max_tool_calls=1` the loop stops after one call and says so.

## Checkpoint
`python -m campus_copilot.cli step 9 --check` runs `tests/steps/test_step_09.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E08 (agent loop, and when not to use one).
