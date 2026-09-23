---
source_id: topic-evaluation
title: Evaluating LLM applications
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Evaluating LLM applications

Illustrative text for a demo system; not official CamTech policy.

## An evaluation set

An evaluation set is a list of labelled cases: an input message, optional history, and the expected behaviour, such as the route, the tools and arguments, whether the system must clarify, abstain, confirm, or block, and the key facts a correct answer contains.

## Metrics

- Route, tool-selection, and argument accuracy for decisions.
- Clarify, abstain, confirm, and block correctness for control behaviour.
- Citation coverage and faithfulness for grounded answers.
- Latency percentiles (p50 and p95) and cost per case.

Results are broken down per category and per language, because an average can hide a weak language or a weak category.

## Judges

Faithfulness needs a judge. A human scorer is the reference but slow. An LLM-as-judge applies a fixed rubric and scales, but has its own biases. A decision model can check each sentence against its cited passage with a closed question. Comparing judges shows where each one disagrees with the others.

## Before and after

An evaluation run is most useful as a comparison: the baseline, then one change, measured on the same cases. A change that helps one category and hurts another shows up only in the per-category table.
