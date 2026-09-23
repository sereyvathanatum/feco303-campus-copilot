---
id: E06
title: Tool calling three ways
week: 7
time_box: 45 min
profiles: [e06_native, e06_json, e06_jev_dispatch]
---
# E06: Tool calling three ways

## Goal
Compare provider tool calling, a JSON protocol, and decision-model dispatch on tool and argument accuracy.

## Steps
1. Run `python -m campus_copilot.cli --profile e06_json eval --subset multi_step,rooms,library` and repeat with the other two profiles.
2. Probe three failure behaviours with each profile: an unknown tool (see `tests/test_graph.py` for a model that proposes one), a missing argument ('Convert 50'), and a wrong type (`--set agent.max_tool_calls=abc` is rejected by validation).
3. Compare the Trace tab of one multi-step turn across the three modes.

## Evidence
| Mode | Tool accuracy | Argument accuracy | Unknown tool | Missing argument | Wrong type |
|---|---|---|---|---|---|

## Questions
1. What does the JSON protocol give up compared with native tool schemas?
2. Where does dispatch by the decision model save a model call?

## Stretch
Add a read tool to `tools/campus.py`, register it, and check that all three modes see the same schema.

Reference results: `experiments/_reference/E06.md`.
