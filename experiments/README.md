# Experiments

Each experiment changes a **profile** (a small TOML file of switches in `profiles/`) instead of the code,
and records evidence from the built-in trace, the evaluation runs in `runs/eval/`, and the Retrieval Lab.

## How an experiment runs

1. Read the sheet: goal, steps, and the evidence table to fill.
2. Run the listed commands. `--profile NAME` selects a profile; `--set KEY=VALUE` changes one key for one run.
3. Copy numbers from the command output, `runs/eval/*.jsonl`, or the UI panels into the evidence table.
4. Answer the questions in two or three sentences each, citing the evidence.
5. Compare with the reference results in `_reference/`, which record the date, run mode, and models used.

Offline mode (no keys) runs every experiment with stub models and recorded fixtures; the stub decider is a
keyword baseline, so decision-model results differ from live runs. Live runs need the keys described in
`docs/setup_keys.md`.

## Worksheet template

```markdown
---
id: EXX
title: ...
week: N
time_box: 45 min
profiles: [...]
---
## Goal
## Steps
## Evidence
| ... |
## Questions
## Stretch
```

## Catalogue

| ID | Week | Title |
|---|---|---|
| E01 | 6 | Prompt anatomy and structured output |
| E02 | 6 | Chunking, token budgets, and silent failures |
| E03 | 6 | Retrieval pipelines, vector stores, and abstention |
| E04 | 7 | Decision-model basics |
| E05 | 7 | Three ways to route |
| E06 | 7 | Tool calling three ways |
| E07 | 7 | Database tools: templates vs text-to-SQL |
| E08 | 7 | Agent loop, and when not to use one |
| E09 | 7 | Memory, follow-ups, and state |
| E10 | 7 | MCP servers |
| E11 | 8 | Evaluation harness and three judges |
| E12 | 8 | Traces, latency, and cost |
| E13 | 8 | Prompt injection and tool-layer safety |
| E14 | 9 | Reading a notice with a vision model |
| E15 | 9 | The decision ladder and an ADR |
