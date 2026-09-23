---
id: E08
title: Agent loop, and when not to use one
week: 7
time_box: 45 min
profiles: [e08_calls_1, baseline, e08_calls_8, e08_agent_on, e08_agent_off]
---
# E08: Agent loop, and when not to use one

## Goal
Put 'when is an agent worth it' in measurable form.

## Steps
1. Run `python -m campus_copilot.cli --profile e08_calls_1 eval --subset multi_step`, then the baseline (4 calls) and `e08_calls_8`.
2. Run single-step categories (timetable, library, currency) with `e08_agent_on` and `e08_agent_off`.
3. Compare tokens and latency in `python -m campus_copilot.cli trace-report --last 40` after each run.
4. Look for loops: the `ad-06` loop-bait case and the repeat detector notes.

## Evidence
| Setting | Multi-step success | Single-step p50 ms | Tokens per turn | Loops caught |
|---|---|---|---|---|

## Questions
1. For which requests does the router path beat the agent on speed and cost?
2. What stopped the loop in each multi-step failure?

## Stretch
Write a request that needs three tools and find the smallest `max_tool_calls` that still answers it.

Reference results: `experiments/_reference/E08.md`.
