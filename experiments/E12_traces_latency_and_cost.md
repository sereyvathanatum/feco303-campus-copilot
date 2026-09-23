---
id: E12
title: Traces, latency, and cost
week: 8
time_box: 45 min
profiles: [baseline, e12_routing, e12_thinking]
---
# E12: Traces, latency, and cost

## Goal
Give latency and cost local numbers, with written assumptions.

## Steps
1. Run `python -m campus_copilot.cli demo`, then `python -m campus_copilot.cli trace-report --last 14`.
2. Repeat with `e12_routing` (small model for simple questions) and `e12_thinking`.
3. Split turn time between the decision model, the chat model, and APIs from the node table.
4. Fill `[prices]` in a copy of the baseline profile with real prices where known; leave unknown prices unknown.

## Evidence
| Setting | Turn p50 / p95 ms | Share: decider / model / APIs | Cost per turn | Cost at 10x (cohort) |
|---|---|---|---|---|

## Questions
1. Why does one decision request per turn matter at about 0.4-0.6 s per request?
2. Which assumption in the cost estimate matters most?

## Stretch
Measure the thought characters recorded in trace spans (`thought_chars`) with and without thinking.

Reference results: `experiments/_reference/E12.md`.
