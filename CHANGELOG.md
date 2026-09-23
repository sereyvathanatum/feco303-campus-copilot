# Changelog

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
