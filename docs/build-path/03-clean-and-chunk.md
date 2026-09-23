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
2. `python -m campus_copilot.cli ingest --show clean --doc campus-handbook`
3. `python -m campus_copilot.cli ingest --show chunk --doc campus-services-faq`

## What to observe
The running header and the page numbers are gone from the cleaned text, and the word broken across a line on the lab-attendance page is joined again. Markdown chunks carry paths such as `Library › How is a loan renewed?`. The chunk report lists the token spread per language: Khmer text needs far more tokens per character than English, which is why chunks are sized in tokens.

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
