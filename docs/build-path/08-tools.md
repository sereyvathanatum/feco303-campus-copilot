---
step: 8
title: Call tools: SQLite and public APIs
week: 7
capability: tools
profile: profiles/steps/step-08.toml
time_box: 60 min
---
# Step 8: Call tools: SQLite and public APIs

## Goal
A chatbot that looks up timetables, rooms, books, weather, exchange rates, and concepts with registered tools.

## Concepts
Tool specs and schemas, selection versus execution, argument filling (select instead of generate), identity from the session, errors as data, attribution, untrusted tool text, read-only SQL with an authorizer.

## Code added in this step
| File | Role |
|---|---|
| `db/` | schema, seed, the read and write connections, query templates |
| `tools/registry.py` | one spec per tool → native, JSON-protocol, and MCP schemas |
| `tools/campus.py` | timetable, deadlines, rooms, books, loans, calendar; the write tools |
| `tools/public_apis.py` | Open-Meteo, ExchangeRate-API, Open Library, Wikipedia |
| `graph/arguments.py` | code extracts amounts, times, and ISBNs; the decider answers closed questions |

## Run it
1. `python -m campus_copilot.cli tools`
2. `python -m campus_copilot.cli step 8 --demo`
3. `python -m campus_copilot.cli ask "bro change 20 dolla to luy khmer"`

## What to observe
Read tools always use the signed-in account; no tool accepts an account ID. A failed API call comes back as a message, not a crash. Every public-API answer names its source. The romanized-Khmer and Khmer-script conversions both reach the currency tool.

## Checkpoint
`python -m campus_copilot.cli step 8 --check` runs `tests/steps/test_step_08.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E06 (tool calling three ways), E07 (templates vs text-to-SQL).
