# feco303-campus-copilot

A complete, runnable Khmer-English campus-support chatbot for a demo campus, built
as a learning pack for LLMs and RAG, decision models, tool calling, agents,
memory, MCP, evaluation, observability, tool-layer security, and multimodal input.

The build plan is `docs/implementation-plan.md`. Build status: `BUILD_PROGRESS.md`.

## Quickstart (offline, no keys)

```bash
python -m venv .venv
# bash / WSL / macOS
.venv/bin/python -m pip install -r requirements.txt
# Windows PowerShell
.venv\Scripts\python -m pip install -r requirements.txt

python -m campus_copilot.cli init-env      # copies .env.example to .env when absent
python -m campus_copilot.cli check         # run mode, .env path, model IDs, reachability
```

With no real keys the app runs in `offline` mode: stub models, a stub decider, and
recorded API fixtures.
