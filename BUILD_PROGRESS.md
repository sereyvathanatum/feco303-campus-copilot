# Build progress ledger

This file is the single resume point for building `feco303-campus-copilot` from
`docs/implementation-plan.md` (plan v5, section 13). Each phase ends with a git
commit in this repository whose subject starts with the phase ID, so
`git log --oneline` and the table below always agree.

## Resume procedure

1. Read the table below and find the first phase whose status is not `done`.
2. Read that phase's notes and the "Next action" line.
3. Run `git status` inside this folder. Uncommitted files belong to the phase in
   progress. Keep them and continue the phase; do not reset.
4. Recreate the virtual environment when `.venv/` is missing:
   `py -3 -m venv .venv` then `.venv/Scripts/python -m pip install -r requirements.txt`.
5. Run `.venv/Scripts/python -m pytest -q` to confirm the finished phases still pass.

## Phase status

| Phase | Scope (plan §13) | Status | Evidence |
|---|---|---|---|
| P0 | scaffold, pins, config, profiles, `cli init-env`/`check`, hooks, CI | done | 15 tests pass; `cli check` prints mode matrix; hook blocked a planted word |
| P1 | campus DB, authorizer, query templates | done | 16 DB tests: seed hash reproducible, authorizer denials, account scoping |
| P2a | ingestion pipeline (7 stages), sources, handbook PDF | done | 19 sources, 117 chunks; offline verify hit@3 0.917, NIM verify hit@3 1.0; re-ingest 0 calls; step 1-4 checkpoints pass |
| P2b | retrieval, stores, grounded answers, step 5 | partly done | 3 stores, 5 modes, `retrieve --compare`, LLM client (NIM + Google, stub fallback), grounded answers, condense; embedding-contract and store-parity tests pass. Remaining: `cli ask` + step-5 checkpoint, built with the P5 graph |
| P3 | decisions: wire, questions, Jev client, stub, LLM router, policy | done | live `jev-smoke` 0.98 in 530 ms; 16 live turn decisions recorded in `data/fixtures/jev/` and replayed in tests; 26 decision tests |
| P4 | tools and public APIs, fixtures | in progress | |
| P5 | graph, memory, agent, confirm, `cli step`/`demo`/`chat` | pending | |
| P6 | MCP servers and transport switch | pending | |
| P7 | Gradio UI | pending | |
| P8 | observability and evaluation | pending | |
| P9 | guards and adversarial controls | pending | |
| P10 | multimodal notice reader | pending | |
| P11 | build-path chapters, experiment sheets, docs | pending | |
| P12 | verify script, budgets, release notes | pending | |

## Next action

P4: `tools/http.py` (session, timeouts, retries, User-Agent, requests-cache, fixture replay),
`tools/registry.py` (one spec per tool -> native, JSON-protocol, MCP schemas), `tools/campus.py`
(DB tools scoped to session account; write tools book_room/place_hold/add_event), `tools/public_apis.py`
(Open-Meteo, ExchangeRate-API, Open Library, Wikipedia; attribution + fetched_at), `tools/text_to_sql.py`
(E07 sandbox), `scripts/record_fixtures.py` (APIs + Jev), `data/api_fixtures/` incl. poisoned variants,
tests: success/empty/error/timeout per tool. Then P5 graph (closes P2b: `cli ask`, step-5 checkpoint).

Graph design already written: `graph/state.py`, `graph/memory.py`, `graph/capabilities.py`,
`observability/trace.py`. Nodes and `graph/build.py` come in P5.

## Build environment notes

- Local interpreter: Python 3.14.6 (Windows). The plan targets 3.10 and 3.12; code
  avoids syntax newer than 3.10, and CI covers 3.10 and 3.12.
- `verify@build` findings are recorded in `docs/verify-at-build.md`.
- Keys live in `.env` (git-ignored): two NVIDIA keys, a Gemini key, an HF token. `COPILOT_CHAT_PROVIDER=google`
  because NIM chat requests timed out on 2026-09-23; NIM embeddings work.
- Code patches: prefer the Edit tool; shell heredocs with backslash escapes corrupted two files once.
