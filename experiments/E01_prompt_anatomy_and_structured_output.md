---
id: E01
title: Prompt anatomy and structured output
week: 6
time_box: 45 min
profiles: [baseline, e01_zero_shot, e01_free_text, e01_hot]
---
# E01: Prompt anatomy and structured output

## Goal
Measure what worked examples, a JSON schema, and temperature change in grounded answers.

## Steps
1. Run `python -m campus_copilot.cli eval --subset handbook,follow_up,unanswerable` with the baseline profile.
2. Repeat with `--profile e01_zero_shot`, `--profile e01_free_text`, and `--profile e01_hot`.
3. Run `python -m campus_copilot.cli --profile e01_hot ask "How long can an approved extension last?"` three times, then the same with the baseline, and compare the wording.
4. Count schema failures: in `runs/eval/*.jsonl`, rows whose answer lacks a valid citation, and trace notes containing `schema failure`.

## Evidence
| Profile | Cases passed | Citation coverage | Schema failures per 10 turns | Answer drift across 3 runs |
|---|---|---|---|---|

## Questions
1. Which failures appear only without the JSON schema?
2. Does temperature 0.8 change facts, or only wording?

## Stretch
Add a third worked example to `llm/prompts.py` (`FEW_SHOT`) that shows a Markdown citation, and re-measure.

Reference results: `experiments/_reference/E01.md`.
