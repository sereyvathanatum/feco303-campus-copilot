# Changelog

## 1.1.0 (unreleased, 23 Sep 2026)

RAG quality fixes found while ingesting a converter-made Markdown document (PDF to Markdown, with tables).

- **Tables:** a Markdown table is split only between rows, and every piece repeats the header row and the
  current group label (`ingest.tables = markdown | rows | text`). Converter artefacts are repaired: padded
  cells, two-row headers for merged column groups, group-label rows, tables with no blank line between them,
  and tables cut at a page break (the header comes from the part before the cut).
- **Context kept in every chunk:** heading levels are rebuilt from numbering when a converter flattened them
  (`## I.` → level 2, `## A)` → level 3); each Markdown chunk starts with a `# Title › Section › Subsection`
  breadcrumb (`ingest.context_header`); list items keep their marker across a split.
- **Re-chunking:** each document stores a chunk recipe (chunker version plus chunk settings); `cli ingest`
  re-chunks unchanged files when the recipe changes.
- **Reranking:** new default mode `hybrid+rerank`: 20 first-stage candidates (`rag.candidates`), reranked by
  `rag.reranker` (`nim` with `llama-nemotron-rerank-vl-1b-v2`, `jev`, or an offline `local` heuristic), top 5
  (`rag.top_k`) sent to the model best first, each `<source>` tagged with `rank` and `relevance`. The Jev
  reranker's verdicts are reused by the passage filter.
- **Verbose logs:** `-v` (one line per step, the retrieval ranking with lexical, dense, fused, and reranker
  scores), `-vv` (every candidate, full prompts and replies), `--log-file`, `COPILOT_LOG_LEVEL`,
  `COPILOT_LOG_FILE`; `ask --show-chunks [--full]`, `chat /chunks` and `/verbose`; the UI Sources panel shows
  rank, relevance, and whether a passage reached the model. Log lines are redacted like traces.
- **Language check:** the Roman numeral one ("Term I", "I. Programs") no longer counts as the pronoun.

## 1.0.0 (unreleased, built 23 Sep 2026)

First complete build of the plan in `docs/implementation-plan.md` (v5), phases P0-P12.

- **Knowledge base:** seven-stage ingestion (gather, extract, clean, chunk, embed, store, verify) over a
  synthetic 20-page PDF handbook and 18 Markdown documents (English and Khmer); token-sized, page- and
  section-aware chunks; embedding cache; incremental and resumable runs; three vector stores.
- **Chatbot:** LangGraph graph driven by capabilities; build path of 12 steps with checkpoints; memory with
  follow-up rewriting; Jev decision model (HTTP, replay) with a keyword stub and an LLM router; policy with
  confidence bands and pooled route confidence; 15 tools over SQLite and four public APIs; bounded agent loop
  in three modes; risk gate and confirm-before-write; MCP servers; notice reading with a vision model.
- **Providers:** NVIDIA NIM and Google AI Studio behind one OpenAI-compatible client with fallback to a
  labelled stub; thought text stripped; timeouts mark a provider unhealthy for five minutes.
- **Safety:** read-only SQL with an authorizer, identity from the session, passage-injection filter,
  untrusted tool-text screen, answer check, layered guards, redacted traces, secret scan.
- **Evaluation and observability:** 77 labelled cases (11 in Khmer script, romanized Khmer, or code-mixed),
  per-category and per-language metrics, three judges, vision field accuracy, trace report with cost at 1x
  and 10x.
- **Learning pack:** 12 build-path chapters, 15 experiment sheets with reference results, Gradio UI with
  decision, source, tool, trace, and memory panels, a Knowledge Base tab, and a Retrieval Lab.
- **Known gaps:** see `docs/verify-at-build.md` (NIM chat unavailable on build day, reranker end of life,
  lunar holidays pending) and `docs/budgets.md` (live chat latency on the AI Studio free tier).

## Unreleased history

- P0 scaffold: pinned requirements, `pyproject.toml`, `.env.example`, configuration loader with placeholder
  detection, profiles, `cli init-env` and `cli check`, language and secret checks, CI workflow, Thunder Client
  collection.
