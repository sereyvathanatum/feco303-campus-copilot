---
id: E03
title: Retrieval pipelines, vector stores, and abstention
week: 6
time_box: 60 min
profiles: [baseline]
---
# E03: Retrieval pipelines, vector stores, and abstention

## Goal
Separate how chunks are scored (lexical, dense, hybrid, reranked, judged) from where vectors are stored and searched (exact vs approximate).

## Steps
1. Fill every available store: `python -m campus_copilot.cli ingest --store all` (Chroma needs `pip install -r requirements-optional.txt`).
2. For 10 handbook questions and 5 unanswerable ones, run `python -m campus_copilot.cli retrieve "QUESTION" --compare` (or the Retrieval Lab tab) and copy the evidence table.
3. Add the judge mode: `python -m campus_copilot.cli retrieve "QUESTION" --mode dense+judge` (a decision-model call per passage).
4. Read `index_ms` and `kb_bytes` from the store stage (`ingest --show store`).

## Evidence
| Mode × store | Context precision (10) | Abstentions correct (5) | Added latency | Top-k overlap vs exact SQLite |
|---|---|---|---|---|

## Questions
1. Where do exact SQLite and `sqlite-vec` disagree, if anywhere?
2. Which mode abstains correctly on the cafeteria question, and why?

## Stretch
Report the reranker column: the NIM reranker reached end of life in August 2026 (docs/verify-at-build.md), so the mode falls back to dense order and says so.

Reference results: `experiments/_reference/E03.md`.
