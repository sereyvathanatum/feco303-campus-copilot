---
id: E02
title: Chunking, token budgets, and silent failures
week: 6
time_box: 60 min
profiles: [baseline, e02_chunk_small, e02_chunk_large, e02_chars, e02_window256, e02_swap, e02_no_pdf]
---
# E02: Chunking, token budgets, and silent failures

## Goal
Show three failures that raise no error: an `input_type` swap, uneven chunks from character budgets across scripts, and truncation by a small embedder window.

## Steps
1. Each chunking profile needs its own knowledge base. Set the runs folder before the commands:
PowerShell `$env:COPILOT_RUNS_DIR = "runs/e02-small"`; bash `export COPILOT_RUNS_DIR=runs/e02-small`.
2. Ingest each profile into its own runs folder: `python -m campus_copilot.cli --profile e02_chunk_small ingest` (then `e02_chunk_large`, `e02_chars`, `e02_window256`, `e02_no_pdf`).
3. For each, read the chunk report: `python -m campus_copilot.cli --profile e02_chars ingest --show chunk` and the `token_spread` in `runs/.../ingest/<run>/run.json` (English vs Khmer).
4. With `e02_window256`, open the `over_window` list: every chunk longer than 256 tokens and the text a truncating embedder would drop.
5. In `nim` mode, ingest with `e02_swap`; compare `python -m campus_copilot.cli --profile e02_swap ingest --show verify` hit@3 with the baseline. No error appears.
6. Retrieval Lab (UI) or `python -m campus_copilot.cli retrieve "What is the yearly tuition fee for Cyber Security?" --compare` for 5 questions per setting.
7. Inspect the image-only prospectus pages: `ingest --show extract --doc camtech-prospectus` and their extraction flags; note which questions those pages could have answered.

## Evidence
| Setting | Chunks | Tokens per chunk (en / km, median) | Chunks over window | Probe hit@3 | Top-3 for 5 questions |
|---|---|---|---|---|---|

## Questions
1. Why does a character budget give Khmer chunks so many more tokens than English chunks?
2. What does the `input_type` swap do to hit@3, and why is there no error?
3. Which answers lose their page citation with `e02_no_pdf`?

## Stretch
A widely copied public RAG demo splits text into 512-token chunks for `all-MiniLM-L6-v2`, which reads only 256 word pieces. Reproduce the loss with `e02_window256` and describe what a reader of that demo never sees.

Reference results: `experiments/_reference/E02.md`.
