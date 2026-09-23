---
source_id: topic-llm-basics
title: Large language models and transformers
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Large language models and transformers

Illustrative text for a demo system; not official CamTech policy.

## What a language model does

A large language model (LLM) predicts the next token of a text, one token at a time, from the tokens before it. Generation repeats that prediction until a stop condition is met. Chat models are language models tuned to follow instructions and to hold a conversation format with system, user, and assistant messages.

## Tokens and the context window

Text reaches a model as tokens: word pieces produced by a tokenizer. English words often map to one or two tokens, while scripts such as Khmer can take several tokens per word. The context window is the maximum number of tokens that the prompt and the reply can share. Anything outside the window is invisible to the model.

## The transformer architecture

Transformers process all tokens of the input in parallel. Self-attention lets every token weigh every other token when building its representation, which captures long-range relations in text. Stacked attention and feed-forward layers produce the representation from which the next token is predicted.

## Limits that shape application design

- Knowledge cut-off: a model knows nothing published after its training data was collected.
- Hallucination: a model can produce fluent statements that no source supports.
- Non-determinism: sampling at a temperature above zero gives different replies to the same prompt.
- Cost and latency grow with the number of input and output tokens.

These limits are the reason applications add retrieval for knowledge, tools for live facts, and evaluation for quality.

## Provider-agnostic use

An application talks to a model through one client interface, so a hosted model, a local model, or a deterministic stub can be swapped without changing the rest of the code. The Campus Copilot uses NVIDIA NIM behind such an interface and falls back to a stub model in offline mode.
