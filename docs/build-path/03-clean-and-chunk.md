---
step: 3
title: Clean and chunk
week: 6
capability: kb (clean, chunk)
profile: profiles/steps/step-03.toml
time_box: 45 min
---
# Step 3: Clean and chunk

## Goal
Clean text split into token-sized chunks that never cross a PDF page and carry a Markdown section path.

## Concepts
Running headers and footers, page numbers, hyphenated line breaks, Unicode NFC, token-based chunk sizing, recursive splitting, header-aware splitting, overlap, the embedder's input window.

## Code added in this step
| File | Role |
|---|---|
| `ingest/clean.py` | removes repeated headers and footers, page numbers, and hyphen breaks; strips HTML comments |
| `ingest/tokens.py` | token counting: the embedder's tokenizer when published, else a labelled approximation |
| `ingest/chunk.py` | page-aware and section-aware chunking; the window check and the chunk report |

## Run it
1. `python -m campus_copilot.cli ingest --until chunk`
2. `python -m campus_copilot.cli ingest --show clean --doc academic-info`
3. `python -m campus_copilot.cli ingest --show chunk --doc academic-info`

## What to observe
The `<!-- image -->` markers the PDF-to-Markdown converter left behind are gone from the cleaned text, and so is the stray page number in the prospectus. Markdown chunks carry heading paths such as `IV. Tuition Fees › A) Bachelor's Degree`, and a table split across chunks repeats its header row in every piece, so a row such as `Cyber Security | $1,350 | ...` still says which column is which. The chunk report lists the token spread per language: Khmer text needs far more tokens per character than English, which is why chunks are sized in tokens.

## Checkpoint
`python -m campus_copilot.cli step 3 --check` runs `tests/steps/test_step_03.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E02.

## Custom-document exercise

Drop one public PDF or Markdown document with a known licence into `data/inbox/`
(or run `python -m campus_copilot.cli ingest add FILE --licence "CC-BY-4.0" --origin "URL"`), re-run
`python -m campus_copilot.cli ingest`, and follow the document through the stage this chapter covers.
After step 5, ask the chatbot a question that only the new document answers.
