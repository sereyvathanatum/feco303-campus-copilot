---
source_id: topic-observability
title: Traces, latency, and cost
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Traces, latency, and cost

Illustrative text for a demo system; not official CamTech policy.

## Traces and spans

A trace records one turn of the application. It is made of spans, one per step, such as routing, retrieval, a tool call, or answer generation. Each span records its start, its duration in milliseconds, the model or tool involved, token counts, and any error.

## Latency

Latency is reported as percentiles. The p50 is the median turn; the p95 is the slow tail that a real user meets once in twenty turns. The share of time per component shows where optimisation pays off: network round trips to a remote decision model, generation time of a language model, or a slow public API.

## Cost

Cost per turn comes from token counts multiplied by the price per million tokens of each model. A cost report states its assumptions, such as turns per session and sessions per term, and scales them, for example to ten times the usage. A price that is not known stays marked as unknown instead of being guessed.

## Redaction

Traces must never contain secrets. A redaction filter masks API keys and personal identifiers before a span is written.
