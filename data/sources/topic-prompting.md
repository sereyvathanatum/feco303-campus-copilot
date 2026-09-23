---
source_id: topic-prompting
title: Prompt design and structured output
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Prompt design and structured output

Illustrative text for a demo system; not official CamTech policy.

## Anatomy of a prompt

A prompt for a chat model usually has four parts: a system message that fixes the role and the rules, context such as retrieved passages or tool results, the request itself, and an output specification. Clear delimiters, for example XML-style tags around sources, keep data apart from instructions.

## Zero-shot and few-shot prompting

A zero-shot prompt states the task without examples. A few-shot prompt adds a small number of worked examples, which fixes the output format and the level of detail more reliably than instructions alone. Examples cost tokens on every call, so the set stays small.

## Temperature

Temperature controls sampling. At temperature 0 the most likely token is chosen at each step, which makes replies nearly repeatable. Higher temperatures give more varied wording and more variation between runs. Grounded question answering normally runs at temperature 0.

## Structured output

Structured output asks the model for data in a schema, such as JSON that matches a Pydantic model, instead of free text. The application validates the reply against the schema and rejects or repairs malformed output. A schema turns a reply into fields that code can check, for example an `abstained` flag and a list of citations.

## Common failure modes

- Instructions buried inside long context are ignored.
- Examples that disagree with the instructions win over the instructions.
- Free-text replies drift in format between runs, which breaks parsers.
- Text inside retrieved documents can carry instructions; it is treated as data, never as a command.
