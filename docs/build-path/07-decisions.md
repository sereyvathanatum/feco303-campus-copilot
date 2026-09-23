---
step: 7
title: Decide with a System One model
week: 7
capability: decisions
profile: profiles/steps/step-07.toml
time_box: 60 min
---
# Step 7: Decide with a System One model

## Goal
A chatbot that routes, clarifies, refuses, and hands off, using typed answers with probabilities from a decision model.

## Concepts
Choice, Noul, and Score answers; confidence bands; one request per turn for guard, route, and arguments; missing details per argument (`not_stated`); pooled confidence for routes with the same action; the rule-based stub as a baseline.

## Code added in this step
| File | Role |
|---|---|
| `decisions/questions.py` | the catalogue of every judgment in the system |
| `decisions/jev.py` | the HTTP client for Jev (`POST /v1/systemone`) |
| `decisions/stub.py` | the keyword-and-regex stub decider (offline, labelled STUB) |
| `decisions/policy.py` | pure functions from a decision to an action |
| `graph/nodes.py` | `guard_and_route`, `apply_policy`, and the fixed replies |

## Run it
1. `python -m campus_copilot.cli decide "Convert 50"`
2. `python -m campus_copilot.cli jev-smoke`
3. `python -m campus_copilot.cli step 7 --demo`

## What to observe
'Convert 50' gets a targeted question about the conversion direction; another account's records and the injection attempt are refused with fixed texts; the fee complaint is handed to the Fees Office. The rewrite now runs only when the `follow_up` Noul fires, so it makes fewer model calls than at step 6.

## Checkpoint
`python -m campus_copilot.cli step 7 --check` runs `tests/steps/test_step_07.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E04 (decision-model basics), E05 (three ways to route).
