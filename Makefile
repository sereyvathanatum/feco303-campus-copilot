# bash / WSL / macOS shortcuts. Windows PowerShell: see README (python -m campus_copilot.cli ...).
PY ?= .venv/bin/python
CLI = $(PY) -m campus_copilot.cli
N ?= 5

.PHONY: env install seed ingest test demo ui check step hooks

env:
	cp -n .env.example .env || true
	@echo ".env at $$(pwd)/.env"

install:
	python3 -m venv .venv
	$(PY) -m pip install -r requirements.txt

seed:
	$(CLI) seed

ingest:
	$(CLI) ingest

test:
	$(PY) -m pytest -q

demo:
	$(CLI) demo

ui:
	$(CLI) ui

check:
	$(CLI) check

step:
	$(CLI) step $(N) --demo

hooks:
	$(PY) scripts/install_hooks.py
