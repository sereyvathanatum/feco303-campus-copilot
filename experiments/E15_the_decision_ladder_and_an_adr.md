---
id: E15
title: The decision ladder and an ADR
week: 9
time_box: 60 min
profiles: [e15_long_context, baseline]
---
# E15: The decision ladder and an ADR

## Goal
Build one feature four ways (long-context prompt, RAG, tool, fine-tuning as a concept) and record the choice in an ADR.

## Steps
1. Answer the handbook cases with the whole handbook in the prompt: `python -m campus_copilot.cli --profile e15_long_context eval --subset handbook`.
2. Answer the same cases with RAG (baseline) and compare quality, latency, and tokens.
3. For a data question (timetable), compare the tool answer with RAG over a handbook that lacks the data.
4. Write fine-tuning down as a concept: what it would change (behaviour) and what it would not (knowledge).
5. Fill `docs/adr_template.md` for the copilot's handbook answers.

## Evidence
| Build | Quality | p50 ms | Tokens per turn | Cost | Effort to update the handbook |
|---|---|---|---|---|---|

## Questions
1. When would long context beat RAG for this campus?
2. What would justify fine-tuning a decision model on the copilot's own routing data?

## Stretch
The optional Laya extension (approval first) fine-tunes an open-weights decision model; list the data it would need.

Reference results: `experiments/_reference/E15.md`.
