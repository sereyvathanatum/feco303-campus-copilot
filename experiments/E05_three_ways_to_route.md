---
id: E05
title: Three ways to route
week: 7
time_box: 45 min
profiles: [e05_keyword, e05_llm, e05_laya, e05_strict, e05_loose]
---
# E05: Three ways to route

## Goal
Compare a keyword rule, an LLM router, and the Laya decision model on the same routing cases.

## Steps
1. Run `python -m campus_copilot.cli --profile e05_keyword eval --subset routing` (the 12 `seed-routing` cases).
2. Repeat with `e05_llm` and `e05_laya`.
3. Extend to the full set: `eval` without `--subset` for each router.
4. Open `runs/eval/` and fill the evidence table; the per-language table is part of every report.
5. Rerun the Laya router with `e05_strict` and `e05_loose` for the threshold question.

## Evidence
| Router | Accuracy (en / km / km-latn) | p50 ms | Cost per 100 turns | Malformed outputs |
|---|---|---|---|---|

## Questions
1. Which messages did only the decision model route correctly, and at what confidence?
2. Which threshold pair gives the lowest error rate without more than 20% clarify replies?

## Stretch
Reword `missing_info` and record the change in clarify rate.

Reference results: `experiments/_reference/E05.md`.
