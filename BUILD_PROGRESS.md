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
| P0 | scaffold, pins, config, profiles, `cli init-env`/`check`, hooks, CI | in progress | |
| P1 | campus DB, authorizer, query templates | pending | |
| P2a | ingestion pipeline (7 stages), sources, handbook PDF | pending | |
| P2b | retrieval, stores, grounded answers, step 5 | pending | |
| P3 | decisions: wire, questions, Jev client, stub, LLM router, policy | pending | |
| P4 | tools and public APIs, fixtures | pending | |
| P5 | graph, memory, agent, confirm, `cli step`/`demo`/`chat` | pending | |
| P6 | MCP servers and transport switch | pending | |
| P7 | Gradio UI | pending | |
| P8 | observability and evaluation | pending | |
| P9 | guards and adversarial controls | pending | |
| P10 | multimodal notice reader | pending | |
| P11 | build-path chapters, experiment sheets, docs | pending | |
| P12 | verify script, budgets, release notes | pending | |

## Next action

Finish P0: write `config.py`, profiles, `cli init-env` and `cli check`, the language
and secret checks, and the CI workflow; then run the P0 definition-of-done checks.

## Build environment notes

- Local interpreter: Python 3.14.6 (Windows). The plan targets 3.10 and 3.12; code
  avoids syntax newer than 3.10, and CI covers 3.10 and 3.12.
- `verify@build` findings are recorded in `docs/verify-at-build.md`.
