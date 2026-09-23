---
step: 5
title: Retrieve and answer: the first chatbot
week: 6
capability: rag
profile: profiles/steps/step-05.toml
time_box: 45 min
---
# Step 5: Retrieve and answer: the first chatbot

## Goal
A chatbot that answers handbook questions from the knowledge base built in steps 1–4, with citations, and abstains otherwise.

## Concepts
Query embedding (`input_type="query"`), top-k retrieval, hybrid retrieval with reciprocal-rank fusion, a grounded prompt, structured output (`GroundedAnswer`), citations, abstention.

## Code added in this step
| File | Role |
|---|---|
| `rag/retrieve.py` | query → scored chunks (lexical, dense, hybrid, rerank, judge) |
| `rag/answer.py` | chunks → `GroundedAnswer` with `[source_id p.N]` or `[source_id § Section]` |
| `llm/` | one client for NIM and Google AI Studio, the stub model, and the prompts |
| `graph/build.py` | at this step: a two-node graph, retrieve → answer |

## Run it
1. `python -m campus_copilot.cli step 5 --chat`
2. `python -m campus_copilot.cli step 5 --demo`

## What to observe
Turn 1 cites the handbook page on lab attendance; turn 3 abstains although the cafeteria page is retrieved. Every non-handbook question also abstains or answers badly: the scoreboard shows which demo turns still fail, and each failure motivates a later step.

## Checkpoint
`python -m campus_copilot.cli step 5 --check` runs `tests/steps/test_step_05.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E01 (prompting), E03 (retrieval pipelines).

## Custom-document exercise

Drop one public PDF or Markdown document with a known licence into `data/inbox/`
(or run `python -m campus_copilot.cli ingest add FILE --licence "CC-BY-4.0" --origin "URL"`), re-run
`python -m campus_copilot.cli ingest`, and follow the document through the stage this chapter covers.
After step 5, ask the chatbot a question that only the new document answers.
