---
step: 11
title: Observe, evaluate, and harden
week: 8
capability: evaluation, guards
profile: profiles/steps/step-11.toml
time_box: 90 min
---
# Step 11: Observe, evaluate, and harden

## Goal
Measured quality, latency, and cost, and a tool layer that holds against bounded, local attacks.

## Concepts
Evaluation sets and per-category, per-language metrics; three faithfulness judges; traces, p50/p95, cost at 1× and 10×; prompt injection (direct and indirect), passage filters, untrusted tool text, answer checks, layered guards.

## Code added in this step
| File | Role |
|---|---|
| `evaluation/` | runner, metrics, judges, vision evaluation |
| `observability/` | spans with redaction, cost accounting, the trace report |
| `data/sources_adversarial/` | the poisoned document (E13 only) |
| `graph/nodes.py` | passage filter, tool-text screen, `verify_answer` |

## Run it
1. `python -m campus_copilot.cli eval`
2. `python -m campus_copilot.cli eval --subset routing --judges`
3. `python -m campus_copilot.cli trace-report`
4. `python -m campus_copilot.cli --profile e13_attacks ingest`
5. `python -m campus_copilot.cli --profile e13_attacks eval --subset adversarial`

## What to observe
The evaluation report breaks every metric down by category and by language. Each adversarial case names the control expected to catch it; `--profile e13_controls_off` shows what gets through without the controls. The trace report keeps unknown prices unknown.

## Checkpoint
`python -m campus_copilot.cli step 11 --check` runs `tests/steps/test_step_11.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E11 (evaluation), E12 (traces and cost), E13 (prompt injection).
