---
source_id: topic-memory-and-state
title: Conversation memory and state
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Conversation memory and state

Illustrative text for a demo system; not official CamTech policy.

## Threads and checkpoints

A chatbot keeps each conversation in a thread. A checkpointer stores the full state of the thread after every turn, so a conversation survives a restart and two threads never see each other's messages.

## The model window

Storing everything does not mean sending everything. Each model call receives a trimmed window: the system message plus the most recent turns, bounded by a turn count and a token budget. Trimming keeps cost and latency stable in long conversations.

## Follow-up questions

A follow-up such as "And the cheaper one?" cannot be searched literally, because the earlier topic is missing from its words. Query rewriting (also called condensing) turns the follow-up into a standalone query, for example "Which of the two phone plans costs less per month?", using the history only to resolve references.

## Rules for safe rewriting

- The rewrite feeds retrieval only; the original message stays in memory and in the answer prompt.
- Codes, numbers, and names from the message must survive the rewrite, or the original message is used instead.
- A rewrite costs a model call, so a gate decides when a message actually depends on history.

## References across turns

Memory also resolves references in actions. After a free-room search, "Book it." refers to a room from the previous result; without memory, the request has no object.
