---
id: E04
title: Decision-model basics
week: 7
time_box: 45 min
profiles: [baseline]
---
# E04: Decision-model basics

## Goal
Read Choice, Noul, and Score answers, and see why a Noul of 0.5 is not 'medium'.

## Steps
1. Run `python -m campus_copilot.cli laya-smoke` and compare the reply with the reference shape in `docs/laya_primer.md`.
2. Run `python -m campus_copilot.cli decide "MESSAGE"` for 8 messages: the 14 demo turns are a good source, plus two of the Khmer ones.
3. Reproduce the `missing_info` comparison of docs/implementation-plan.md §8.3: change its wording in `decisions/questions.py` to the generic and the conversion-specific versions and record the Noul for 'Convert 50' and for complete requests.
4. Offline, `decide --decider keyword` shows the stub's answers for the same messages.

## Evidence
| Message | route (confidence) | currency_direction | amount_stated | missing_info | Policy action |
|---|---|---|---|---|---|

## Questions
1. Why does a per-argument `not_stated` option catch 'Convert 50' better than one generic question?
2. What does a route split such as 0.60 / 0.39 mean for the policy?

## Stretch
Add a new Noul to `questions.py`, check it with `decide`, and write down how its wording changed the answer.

Reference results: `experiments/_reference/E04.md`.
