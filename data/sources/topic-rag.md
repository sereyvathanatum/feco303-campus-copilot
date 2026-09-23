---
source_id: topic-rag
title: Retrieval-augmented generation
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Retrieval-augmented generation

Illustrative text for a demo system; not official CamTech policy.

## The idea

Retrieval-augmented generation (RAG) answers a question in two steps. First, a retriever finds passages related to the question in a document collection. Second, a language model writes an answer using only those passages. RAG supplies knowledge that the model never saw in training and keeps answers tied to approved documents.

## The pipeline

Before any question arrives, documents are gathered, their text is extracted, cleaned, split into chunks, embedded, and stored. At question time, the question is embedded, the closest chunks are retrieved, and a grounded prompt asks the model to answer from those chunks.

## Grounding and citations

A grounded answer states only what the retrieved passages support and cites each fact, for example with a document ID and a page number. Citations let a reader check the answer against the source.

## Abstention

When the retrieved passages do not contain the answer, the correct behaviour is to say so instead of guessing. A retrieved passage is not always a relevant passage: a question about the price of a train ticket can retrieve a passage about train timetables, which does not answer it.

## Where RAG fails

- The right chunk is never retrieved, because of poor chunking or a weak query.
- The right chunk is retrieved but ranked below irrelevant ones.
- The model ignores the passages and answers from memory.
- A follow-up question such as "and on weekends?" is searched literally, without the earlier topic, unless it is rewritten first.
