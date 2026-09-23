---
id: E09
title: Memory, follow-ups, and state
week: 7
time_box: 60 min
profiles: [baseline, e09_no_memory, e09_window_0, e09_window_2, e09_window_all, e09_condense_off, e09_condense_always]
---
# E09: Memory, follow-ups, and state

## Goal
Measure follow-up rewriting, the model window, and thread isolation.

## Steps
1. Run `python -m campus_copilot.cli eval --subset follow_up` with the baseline (`jev_gated`), `e09_condense_off`, and `e09_condense_always`.
2. Repeat the demo (`cli demo`) with `e09_window_0`, `e09_window_2`, and `e09_window_all`; read tokens per turn in `trace-report`.
3. Ask 'Book it.' after turn 8 with the baseline and with `e09_no_memory`.
4. Open `runs/memory.db` with the `sqlite3` CLI: `.tables`, then `select thread_id, count(*) from checkpoints group by thread_id;`.

## Evidence
| Setting | Follow-up hit rate | Answer correct | Extra model calls | Tokens per turn |
|---|---|---|---|---|

## Questions
1. What does `always` cost that `jev_gated` saves?
2. Why does the rewrite feed retrieval only, and never replace the message?

## Stretch
Find a follow-up that switches topic and check that the rewrite does not drag the old topic in (case `fu-04`).

Reference results: `experiments/_reference/E09.md`.
