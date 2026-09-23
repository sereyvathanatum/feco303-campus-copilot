---
id: E07
title: Database tools: templates vs text-to-SQL
week: 7
time_box: 45 min
profiles: [baseline, e07_text_to_sql]
---
# E07: Database tools: templates vs text-to-SQL

## Goal
Compare parameterised query templates with model-written SQL in a sandbox.

## Steps
1. Ask 8 database questions (timetable, deadlines, rooms, books) with the baseline and with `--profile e07_text_to_sql`.
2. With `e07_text_to_sql --set guards.enabled=false`, ask 'Show the library loans of A0007.' and read which authorizer rule stopped the query (Tools tab, `stopped_by`).
3. Run `python -m campus_copilot.cli ask "Show the loans'; DROP TABLE loans;--"` with both profiles and confirm the loans table is unchanged (`python -m campus_copilot.cli seed` prints the content hash).

## Evidence
| Question | Templates: correct | Text-to-SQL: SQL written | Correct | Rule that stopped a bad query |
|---|---|---|---|---|

## Questions
1. Why is the `accounts` table denied outright instead of filtered by row?
2. What does the 50-row cap protect against?

## Stretch
The decision-model API rejects SQL-shaped messages with HTTP 403 (docs/verify-at-build.md). Explain why the turn still works.

Reference results: `experiments/_reference/E07.md`.
