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
| P4 | tools and public APIs, fixtures | done | 15 tools (10 campus incl. 3 writes, 4 public APIs, run_sql); live fixtures recorded 23 Sep 2026 + poisoned Wikipedia variant; 29 tool tests (success, empty, error, timeout) |
| P5 | graph, memory, agent, confirm, `cli step`/`demo`/`chat` | in progress | |
| P6 | MCP servers and transport switch | pending | |
| P7 | Gradio UI | pending | |
| P8 | observability and evaluation | pending | |
| P9 | guards and adversarial controls | pending | |
| P10 | multimodal notice reader | pending | |
| P11 | build-path chapters, experiment sheets, docs | pending | |
| P12 | verify script, budgets, release notes | pending | |

## Next action

P5: `data/demo_turns.jsonl` (14 turns + expected checks), `graph/arguments.py` (decision + regex -> tool args),
`graph/nodes.py`, `graph/agent.py` (3 modes, repeat detector, max calls), risk gate + `interrupt()` confirm,
`graph/build.py` (`Copilot.ask/resume`, SqliteSaver in runs/memory.db, capability-driven wiring, Mermaid export),
`graph/demo.py` (scoreboard), `cli ask|chat|step N [--demo|--check|--chat]|demo|tools`, tests incl. step 5-10
checkpoints and the expected scoreboard 2/3/7/11/13/13 (steps 5-10). This also closes P2b.

Graph design already written: `graph/state.py`, `graph/memory.py`, `graph/capabilities.py`,
`observability/trace.py`. Nodes and `graph/build.py` come in P5.

## Build environment notes

- Local interpreter: Python 3.14.6 (Windows). The plan targets 3.10 and 3.12; code
  avoids syntax newer than 3.10, and CI covers 3.10 and 3.12.
- `verify@build` findings are recorded in `docs/verify-at-build.md`.
- Keys live in `.env` (git-ignored): two NVIDIA keys, a Gemini key, an HF token. `COPILOT_CHAT_PROVIDER=google`
  because NIM chat requests timed out on 2026-09-23; NIM embeddings work.
- Code patches: prefer the Edit tool; shell heredocs with backslash escapes corrupted two files once.
