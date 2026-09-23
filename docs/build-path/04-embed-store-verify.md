---
step: 4
title: Embed, store, and verify
week: 6
capability: kb (complete)
profile: profiles/steps/step-04.toml
time_box: 45 min
---
# Step 4: Embed, store, and verify

## Goal
A verified knowledge base: vectors cached per chunk, stored in SQLite (and optionally sqlite-vec or Chroma), with probe questions that find their source.

## Concepts
Asymmetric embeddings (`passage` vs `query`), `truncate=NONE`, an embedding cache keyed by content hash, incremental ingestion, vector stores behind one interface, FTS5 lexical index, probe hit@k.

## Code added in this step
| File | Role |
|---|---|
| `ingest/embed.py` | embeds only chunks without a cached vector for the current model |
| `ingest/store.py` | `kb.db` tables, upserts and deletions, FTS5, and every selected vector backend |
| `ingest/verify.py` | row-count consistency, metadata completeness, probe hit@k |
| `rag/embeddings.py` | NIM embedder over HTTP and the offline hashing encoder |
| `rag/stores/` | SQLite + NumPy (default), `sqlite-vec`, Chroma (optional) |

## Run it
1. `python -m campus_copilot.cli ingest`
2. `python -m campus_copilot.cli ingest`
3. `python -m campus_copilot.cli ingest --store all`
4. `python -m campus_copilot.cli ingest --show verify`

## What to observe
The second run reports zero embedding calls: every vector comes from the cache. Editing one Markdown file and running again re-embeds only that file's chunks. In `nim` mode the gather stage prints a notice that chunk text goes to NVIDIA's hosted API; `--profile offline` keeps everything on the machine.

## Checkpoint
`python -m campus_copilot.cli step 4 --check` runs `tests/steps/test_step_04.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E02, E03.

## Custom-document exercise

Drop one public PDF or Markdown document with a known licence into `data/inbox/`
(or run `python -m campus_copilot.cli ingest add FILE --licence "CC-BY-4.0" --origin "URL"`), re-run
`python -m campus_copilot.cli ingest`, and follow the document through the stage this chapter covers.
After step 5, ask the chatbot a question that only the new document answers.
