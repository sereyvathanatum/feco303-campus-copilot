---
id: E14
title: Reading a notice with a vision model
week: 9
time_box: 45 min
profiles: [baseline]
---
# E14: Reading a notice with a vision model

## Goal
Measure field accuracy per image and see which fields the decision model flags.

## Steps
1. Regenerate the image set if needed: `python scripts/make_images.py`.
2. Run `python -m campus_copilot.cli eval --vision` offline, then in a mode with a live vision model.
3. Try each image in the UI or with `python -m campus_copilot.cli ask --image data/images/poster_blurred.png "Add this to the calendar."`.
4. Record the failure type for each image: blur, rotation, Khmer script, dense table.

## Evidence
| Image | Field accuracy | Fields flagged | Wrong and not flagged | Failure type |
|---|---|---|---|---|

## Questions
1. Which failure did the per-field check miss, and which did a code check catch?
2. Why is an extracted event a proposal, not a write?

## Stretch
Add a sixth image variant to `scripts/make_images.py` (for example low contrast) with its ground truth.

Reference results: `experiments/_reference/E14.md`.
