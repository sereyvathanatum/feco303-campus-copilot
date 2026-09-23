---
source_id: topic-embeddings-vector-search
title: Embeddings and vector search
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Embeddings and vector search

Illustrative text for a demo system; not official CamTech policy.

## Embeddings

An embedding model maps a text to a vector of numbers so that texts with similar meaning land close together. Closeness is usually measured by cosine similarity, the cosine of the angle between two vectors.

## Asymmetric embedding models

Some embedding models are asymmetric: stored passages are embedded with the input type `passage`, and search queries with the input type `query`. Swapping the two raises no error, but retrieval quality drops quietly. The only defence is a test that checks the input type sent with each request.

## Input limits and truncation

Every embedding model has a maximum input length in tokens. Some services truncate longer inputs silently and embed only the beginning, so the end of a long chunk never influences retrieval. Requesting an error instead of truncation makes the problem visible.

## Exact and approximate search

Exact search compares the query vector with every stored vector. It is simple and correct, and fast enough for thousands of chunks. Approximate nearest-neighbour indexes such as HNSW trade a little accuracy for speed on millions of vectors; their top results can differ from exact search.

## Lexical, dense, and hybrid retrieval

Lexical retrieval scores shared words, for example with BM25, and handles codes, numbers, and names well. Dense retrieval uses embeddings and handles paraphrases. Hybrid retrieval fuses both rankings, for example with reciprocal-rank fusion, and is a strong default.
