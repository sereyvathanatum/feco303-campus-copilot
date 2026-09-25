---
step: 2
title: Extract text from PDF and Markdown
week: 6
capability: kb (extract)
profile: profiles/steps/step-02.toml
time_box: 30 min
---
# Step 2: Extract text from PDF and Markdown

## Goal
Plain text per PDF page and per Markdown file, with page numbers and frontmatter metadata kept.

## Concepts
PDF text layers, 1-based page numbers for citations, YAML frontmatter, script detection, the limits of PDF extraction for complex scripts, scanned PDFs without a text layer (OCR is out of scope).

## Code added in this step
| File | Role |
|---|---|
| `ingest/extract.py` | `pypdf` text per page; Markdown bodies with frontmatter metadata; extraction checks |

## Run it
1. `python -m campus_copilot.cli ingest --until extract`
2. `python -m campus_copilot.cli ingest --until extract --show extract --doc camtech-prospectus`

## What to observe
The prospectus yields one record per page. It is a designed brochure, so several pages are a photograph with no text layer: those come out empty and are flagged, because a scanned or image-only page needs OCR, which is out of scope here. Where the text layer exists, extraction keeps its flaws (`Cam Tech`, stray symbols such as `~`), and those flaws reach the chunks. The Markdown file (`Academic_Info.md`) is one record with no page numbers; its structure lives in the headings. Metadata comes from `data/sources/manifest.csv`, or from YAML frontmatter when a Markdown file has one.

## Checkpoint
`python -m campus_copilot.cli step 2 --check` runs `tests/steps/test_step_02.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E02.

## Custom-document exercise

Drop one public PDF or Markdown document with a known licence into `data/inbox/`
(or run `python -m campus_copilot.cli ingest add FILE --licence "CC-BY-4.0" --origin "URL"`), re-run
`python -m campus_copilot.cli ingest`, and follow the document through the stage this chapter covers.
After step 5, ask the chatbot a question that only the new document answers.
