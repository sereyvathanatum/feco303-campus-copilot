# ADR-NNN: Title of the decision

- **Status:** proposed | accepted | superseded by ADR-MMM
- **Date:** YYYY-MM-DD
- **Scope:** the feature or component the decision covers (for example "handbook answers", "room booking")

## Context

What problem the feature solves, for which requests, and under which constraints: data that changes,
languages (English, Khmer script, romanized Khmer), latency and cost budgets (docs/implementation-plan.md §11),
privacy of the data, and what a wrong answer costs.

## Options

Each option is measured on the same cases (E15 builds the same feature four ways):

| Option | Quality (metric, cases) | p50 / p95 latency | Cost per 100 turns | Effort to change | Notes |
|---|---|---|---|---|---|
| Long-context prompt (whole document in context) | | | | | |
| Retrieval (RAG) | | | | | |
| Tool or database lookup | | | | | |
| Fine-tuning (conceptual only) | not measured | | | | behaviour, not knowledge |

Evidence: `runs/eval/<profile>-<timestamp>.jsonl`, `cli trace-report`, and the E15 worksheet.

## Decision

The option chosen, in one sentence, and the measured reason it wins for this scope.

## Consequences

- What becomes easier (for example: a handbook change is one `cli ingest` run).
- What becomes harder or riskier (for example: retrieval misses on paraphrases; a new failure to monitor).
- Which metric and threshold will show that the decision needs revisiting.
- Follow-up work, owners, and dates.
