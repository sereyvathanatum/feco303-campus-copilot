---
step: 1
title: Gather sources
week: 6
capability: kb (gather)
profile: profiles/steps/step-01.toml
time_box: 30 min
---
# Step 1: Gather sources

## Goal
A listed, hashed, and licence-checked set of source documents: the raw material of the knowledge base.

## Concepts
Document inventory, content hashes (SHA-256), licence and origin metadata, change detection (new, changed, unchanged, removed), drop folders.

## Code added in this step
| File | Role |
|---|---|
| `ingest/manifest.py` | reads and writes `manifest.csv`; `ingest add` copies a file into `data/inbox/` and records it |
| `ingest/gather.py` | scans the source folders, hashes every file, compares with the knowledge base, flags problems |
| `data/sources/` | the pack's own PDF and Markdown documents, `manifest.csv`, `probes.jsonl` |
| `data/inbox/` | the drop folder; its contents are git-ignored |

## Run it
1. `python -m campus_copilot.cli ingest --until gather`
2. `python -m campus_copilot.cli ingest --show gather`
3. `python -m campus_copilot.cli ingest add path/to/notice.pdf --licence "CC-BY-4.0" --origin "https://example.org/notice.pdf"`

## What to observe
Every pack document appears with its hash and status. A file added without a licence carries the flag `licence unknown`. A second copy of the same file is flagged as a duplicate. The stage table in the UI (Knowledge Base tab) shows the same rows.

## Checkpoint
`python -m campus_copilot.cli step 1 --check` runs `tests/steps/test_step_01.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E02 (chunking and silent failures).

## Custom-document exercise

Drop one public PDF or Markdown document with a known licence into `data/inbox/`
(or run `python -m campus_copilot.cli ingest add FILE --licence "CC-BY-4.0" --origin "URL"`), re-run
`python -m campus_copilot.cli ingest`, and follow the document through the stage this chapter covers.
After step 5, ask the chatbot a question that only the new document answers.
