---
source_id: topic-chunking
title: Chunking documents for retrieval
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Chunking documents for retrieval

Illustrative text for a demo system; not official CamTech policy.

## Why documents are chunked

Retrieval returns chunks, not whole documents. A chunk must be small enough to be specific and to fit the embedding model, and large enough to carry a complete statement.

## Measuring size in tokens

Chunk size measured in characters gives unequal token counts across scripts: the same number of characters is far more tokens in Khmer script than in English. Measuring chunk size in tokens, with the tokenizer of the embedding model, keeps chunks comparable across languages and makes embedding cost predictable.

## Structure-aware splitting

- PDF text is split within a page and never across pages, so each chunk keeps a page number for citation.
- Markdown is first split at headings, so each chunk carries a section path such as "Library rules > Loans", and then split by size inside each section.
- A recursive splitter tries paragraph breaks first, then sentences, then words.

## Overlap

A small overlap between neighbouring chunks keeps a sentence that straddles a boundary retrievable from either side. Large overlaps waste storage and return near-duplicate chunks.

## The window check

Before embedding, every chunk is compared with the input window of the embedding model. A chunk longer than the window is listed with the text a truncating model would drop. A well-known public demo split text into 512-token chunks for a model that reads only 256 word pieces, so half of every chunk was never embedded and nothing reported it.
