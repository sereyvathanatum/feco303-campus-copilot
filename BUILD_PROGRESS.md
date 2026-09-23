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
| P2b | retrieval, stores, grounded answers, step 5 | done | 3 stores, 5 modes, `retrieve --compare`, LLM client (NIM + Google, stub fallback), grounded answers, condense; `cli ask` and step-5 checkpoint landed with P5 |
| P3 | decisions: wire, questions, Jev client, stub, LLM router, policy | done | live `jev-smoke` 0.98 in 530 ms; 16 live turn decisions recorded in `data/fixtures/jev/` and replayed in tests; 26 decision tests |
| P4 | tools and public APIs, fixtures | done | 15 tools (10 campus incl. 3 writes, 4 public APIs, run_sql); live fixtures recorded 23 Sep 2026 + poisoned Wikipedia variant; 29 tool tests (success, empty, error, timeout) |
| P5 | graph, memory, agent, confirm, `cli step`/`demo`/`chat` | done | offline scoreboard 2/3/7/11/13/13 at steps 5-10 exactly as planned; 3 agent modes; confirm/cancel; checkpoints 5-9; 146 tests |
| P6 | MCP servers and transport switch | done | 2 stdio servers from registry specs (no write tools), identity via `_meta`, resources; 12-call parity test; step-10 scoreboard identical over MCP |
| P7 | Gradio UI | done | chat + 5 panels, Knowledge Base, Retrieval Lab, Confirm/Cancel; binds 127.0.0.1 (checked); turn driven over HTTP; `docs/ui-checklist.md`; live Jev demo 13/14 (turn 13 needs P10) |
| P8 | observability and evaluation | done | 77 eval cases (11 local-language, 12 seed-routing); offline eval 3 s, 56/75 pass with the keyword stub; per-category and per-language tables; trace report with 1x/10x cost, unknown prices kept unknown; 3 judges |
| P9 | guards and adversarial controls | done | poisoned document + poisoned API fixture; passage filter, tool-text filter, severity guard; 7/7 adversarial cases caught by their control offline and with live Jev; controls-off profile shows each attack succeed; step-11 checkpoint |
| P10 | multimodal notice reader | done | 5 synthetic images + manifest; reader with per-field decision checks and a time-range check; offline step 12 = 14/14; live Gemma 4 read the clean and Khmer posters correctly (Jev 0.97-0.99 per field); E14 table via `cli eval --vision` |
| P11 | build-path chapters, experiment sheets, docs | in progress | ADR template written with P10 |
| P12 | verify script, budgets, release notes | pending | |

## Next action

P11 (docs; all text impersonal, checked by `scripts/check_language.py`):
- `docs/build-path/01-...md` to `12-...md` (template: plan §10.1; no numbers that checkpoints compute);
- `experiments/README.md` + `E01`..`E15` sheets (template: plan §10.2) + the experiment profiles they name;
- `experiments/_reference/` results (run offline; live where keys allow);
- `docs/architecture.md` (exported Mermaid per step), `docs/setup_keys.md`, `docs/jev_primer.md`
  (reference call + response shape), `docs/troubleshooting.md`; README tour.
Then P12: `scripts/verify.py`, budget check, live smoke, CHANGELOG, tag.

## Build environment notes

- Local interpreter: Python 3.14.6 (Windows). The plan targets 3.10 and 3.12; code
  avoids syntax newer than 3.10, and CI covers 3.10 and 3.12.
- `verify@build` findings are recorded in `docs/verify-at-build.md`.
- Keys live in `.env` (git-ignored): two NVIDIA keys, a Gemini key, an HF token. `COPILOT_CHAT_PROVIDER=google`
  because NIM chat requests timed out on 2026-09-23; NIM embeddings work.
- Code patches: prefer the Edit tool; shell heredocs with backslash escapes corrupted two files once.
