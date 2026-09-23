---
id: E13
title: Prompt injection and tool-layer safety
week: 8
time_box: 60 min
profiles: [e13_attacks, e13_controls_off]
---
# E13: Prompt injection and tool-layer safety

## Goal
Run bounded attacks against the copilot's own data and record which control stops each one.

## Steps
1. Ingest the poisoned document: `python -m campus_copilot.cli --profile e13_attacks ingest`.
2. Run `python -m campus_copilot.cli --profile e13_attacks eval --subset adversarial` and read the `control` column.
3. Repeat with `--profile e13_controls_off` and record what gets through.
4. Change one threshold (for example `--set guards.block=0.99`) and rerun: the review flag plus severity still refuses.
5. Only the repository's own documents, fixtures, and synthetic data are attacked; no live external system is a target.

## Evidence
| Attack | Behaviour (controls on) | Control that caught it | Behaviour (controls off) | Severity | OWASP label |
|---|---|---|---|---|---|

## Questions
1. Which control is a switch, and which is built into the design (templates, loop limits, session identity)?
2. Why does the poisoned Wikipedia text only appear with recorded fixtures?

## Stretch
Write one new adversarial case in `eval/cases.jsonl` with an `expected_control` and make it pass.

Reference results: `experiments/_reference/E13.md`.
