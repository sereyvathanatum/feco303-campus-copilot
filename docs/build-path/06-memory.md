---
step: 6
title: Remember the conversation
week: 7
capability: memory
profile: profiles/steps/step-06.toml
time_box: 45 min
---
# Step 6: Remember the conversation

## Goal
A chatbot that keeps each conversation in a thread and understands follow-up questions.

## Concepts
Threads and checkpoints (`SqliteSaver`), the model window (`trim_messages`), follow-up rewriting before retrieval, keeping the original message next to the rewrite.

## Code added in this step
| File | Role |
|---|---|
| `graph/memory.py` | the trimmed model window and the decision model's short history |
| `rag/condense.py` | the rewrite, its gate modes, and the guard that codes and numbers survive |
| `graph/state.py` | the persisted state of a thread |

## Run it
1. `python -m campus_copilot.cli step 6 --demo`
2. `python -m campus_copilot.cli step 6 --chat`

## What to observe
Turn 2 ('And for a master's degree?') is rewritten into a standalone query; the Sources panel shows the original next to the rewrite. At this step the rewrite runs on every RAG turn with history (`always`). A new thread has no history, so the same follow-up is searched literally.

## Checkpoint
`python -m campus_copilot.cli step 6 --check` runs `tests/steps/test_step_06.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E09 (memory, follow-ups, and state).
