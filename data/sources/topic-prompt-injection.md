---
source_id: topic-prompt-injection
title: Prompt injection and tool-layer safety
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Prompt injection and tool-layer safety

Illustrative text for a demo system; not official CamTech policy.

## Direct and indirect injection

Direct prompt injection arrives in the message itself, for example a request to ignore previous rules or to print hidden instructions. Indirect injection hides instructions inside content that the application reads: a retrieved document, a web page, or an API result.

## Controls at the tool layer

- A guard question checks each message for attempts to change or reveal the rules.
- A passage filter drops retrieved chunks that contain instructions aimed at the assistant.
- Tool results are wrapped in tags and treated as data, never as instructions.
- Database access is read-only by default, with an allow-list of tables and columns.
- Tools take the account from the session, so a message cannot widen access.
- Write actions pass a risk gate and wait for an explicit confirmation.
- Agent loops stop at a fixed number of tool calls.

## Red-teaming within bounds

Adversarial tests use the application's own documents, fixtures, and synthetic data. Each test records the attack, the behaviour, the control that caught it, and a severity. OWASP Top 10 for LLM applications labels, such as LLM01 for prompt injection, classify the cases.

## Thresholds

Guard decisions use thresholds: a high score blocks, a middle score lets the turn continue but flags it for review. Every threshold change is re-tested against the same adversarial cases.
