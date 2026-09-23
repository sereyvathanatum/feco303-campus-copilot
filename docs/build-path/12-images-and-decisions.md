---
step: 12
title: Images and the architecture decision
week: 9
capability: vision
profile: profiles/steps/step-12.toml
time_box: 60 min
---
# Step 12: Images and the architecture decision

## Goal
A photographed notice becomes a confirmed calendar event, and the copilot's own design is recorded in an ADR.

## Concepts
Vision-language models, structured extraction, field verification against the transcription, code checks (time ranges), confirmation before writes, the decision ladder (prompt, long context, RAG, tools, fine-tuning), ADRs.

## Code added in this step
| File | Role |
|---|---|
| `multimodal/notice_reader.py` | VLM reading, per-field decision checks, blanking |
| `scripts/make_images.py` | synthetic posters and a timetable photo with ground truth |
| `docs/adr_template.md` | the architecture decision record template |

## Run it
1. `python -m campus_copilot.cli step 12 --demo`
2. `python -m campus_copilot.cli ask --image data/images/poster_clean.png "Add this to the calendar."`
3. `python -m campus_copilot.cli eval --vision`

## What to observe
The clean poster becomes a pending event; Confirm writes it. The blurred, rotated, and Khmer posters produce questions about the fields that could not be verified instead of a wrong event.

## Checkpoint
`python -m campus_copilot.cli step 12 --check` runs `tests/steps/test_step_12.py`. Read its output for the numbers; this chapter
quotes none, so it cannot drift from the code.

## Go deeper
E14 (reading a notice), E15 (the decision ladder and an ADR).
