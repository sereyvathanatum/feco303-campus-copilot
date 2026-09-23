---
source_id: topic-multimodal
title: Vision-language models
language: en
licence: CC-BY-4.0 (written for this pack)
---
# Vision-language models

Illustrative text for a demo system; not official CamTech policy.

## Images as input

A vision-language model (VLM) accepts images together with text. The image is encoded into tokens that the language model attends to, so a single prompt can ask for a transcription, a description, or structured fields extracted from a photo.

## Extraction with verification

Reading a photographed notice works best in two steps. First, the VLM returns a plain transcription and a structured draft, such as an event with title, date, start time, end time, and location. Second, each field is checked against the transcription; a field that the transcription does not support is blanked and asked for.

## Typical failures

- Blur and low resolution hide digits in dates and times.
- Rotation and perspective confuse reading order.
- Dense tables mix up rows and columns.
- Complex scripts, such as Khmer, are read less reliably than Latin script.

## Human confirmation

An extracted event is a proposal. It is written to a calendar only after an explicit confirmation, like every other write action.
