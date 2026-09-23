---
source_id: topic-fine-tuning-vs-rag
title: Prompting, RAG, tools, or fine-tuning
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Prompting, RAG, tools, or fine-tuning

Illustrative text for a demo system; not official CamTech policy.

## The decision ladder

Each rung adds cost and complexity, so a feature climbs only as far as it must:

1. Prompting: instructions and a few examples change format and tone.
2. Long context: a small, stable document fits whole into the prompt.
3. Retrieval (RAG): a larger or changing collection is searched per question.
4. Tools: live or personal facts come from databases and APIs.
5. Fine-tuning: training changes the model's behaviour itself.

## Behaviour versus knowledge

Fine-tuning changes behaviour: style, format, or a narrow classification skill. RAG supplies knowledge that changes over time and needs citations. Updating a handbook is an ingestion run with RAG, but a new training run with fine-tuning.

## Parameter-efficient fine-tuning

PEFT methods train a small number of added parameters instead of the whole model. LoRA adds low-rank matrices to selected layers; QLoRA does the same on a quantised base model to save memory. DPO trains on pairs of preferred and rejected answers.

## Recording the choice

An architecture decision record (ADR) states the context, the options considered, the decision, and its consequences, with measured quality, latency, and cost for each option.
