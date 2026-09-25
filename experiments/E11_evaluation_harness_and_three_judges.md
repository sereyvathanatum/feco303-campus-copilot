---
id: E11
title: Evaluation harness and three judges
week: 8
time_box: 60 min
profiles: [baseline, e11_lexical]
---
# E11: Evaluation harness and three judges

## Goal
Measure one change against the baseline and compare three faithfulness judges.

## Steps
1. Run `python -m campus_copilot.cli eval --judges` with the baseline and with `--profile e11_lexical`.
2. Compare the per-category tables before and after.
3. Score 10 answered cases by hand in `eval/manual_scoring.csv` (1-5), then rerun `eval --judges` to add the human judge.
4. Read the disagreement report at the end of the run.

## Evidence
| Category | Baseline passed | After change | Human | LLM judge | Laya judge |
|---|---|---|---|---|---|

## Questions
1. Where do the human, LLM, and decision-model judges disagree, and who is right?
2. Which category got better and which got worse with the change?

## Stretch
Add three evaluation cases in Khmer script and rerun the per-language table.

Reference results: `experiments/_reference/E11.md`.
