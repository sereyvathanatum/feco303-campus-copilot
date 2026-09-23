---
source_id: topic-agents
title: Agent loops
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Agent loops

Illustrative text for a demo system; not official CamTech policy.

## The ReAct pattern

An agent loop alternates between reasoning and acting. At each step the model reads the request and the results so far, then either calls one more tool or writes the final answer. The pattern is often called ReAct, for reason and act.

## Stopping rules

A loop needs hard limits: a maximum number of tool calls per turn, and a detector that stops the loop when the same tool is called twice with the same arguments. Without limits, a confused model can call tools until a budget runs out.

## Three ways to drive the loop

- Native tool calling uses the provider's tool API and its schema validation.
- A JSON protocol asks any chat model for exactly one JSON object per step, either a tool call or a final answer, and parses it tolerantly.
- Decision-model dispatch lets a decision model pick the next tool and fill closed-set arguments, while the language model writes only the final answer.

## When an agent is worth it

Agents help when a request needs information from several sources, such as a free-room search followed by a weather check. For a single lookup, a router that calls one tool directly is faster, cheaper, and easier to test. Measuring both paths on the same questions settles the choice.
