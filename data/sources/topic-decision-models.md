---
source_id: topic-decision-models
title: System One decision models
language: en
licence: CC-BY-4.0 (written for this pack)
---
# System One decision models

Illustrative text for a demo system; not official CamTech policy.

## Judgment without generation

A System One decision model answers closed questions about a piece of state and returns typed answers with probabilities instead of free text. Code owns the workflow and asks the decision model only at the branch points, for example which kind of request a message is, or whether a passage answers a query.

## Three answer types

- A Choice picks one option from a fixed set and returns a probability for every option.
- A Noul returns one number between 0 and 1 for a yes-or-no question.
- A Score places the state on an ordered scale of 2 to 10 levels.

A Noul of 0.5 is not "medium": it means the model cannot tell yes from no.

## Confidence and bands

A Choice with probabilities 0.49 and 0.51 has a winner but low confidence. Applications set bands: above a high threshold the answer is acted on, between the thresholds the application asks a clarifying question before any risky step, and below the low threshold it clarifies or falls back.

## One request, many questions

Guard, route, and argument questions are independent questions over the same state, so they are sent together in one request and answered in parallel. Code reads only the answers that apply to the chosen branch.

## Missing details

A single "is information missing?" question gives many false alarms. Asking per argument works better: every closed-set argument has a `not_stated` option, and short yes-or-no questions check whether an amount or a time appears at all. Exact numbers are extracted by code, not by the decision model.
