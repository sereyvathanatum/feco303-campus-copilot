"""Shared test setup: no network, no real keys, a pinned campus clock, isolated run folders."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
_real_connect = socket.socket.connect
_real_create_connection = socket.create_connection


def _host_of(address) -> str:
    return address[0] if isinstance(address, tuple) else str(address)


def _guarded_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and _host_of(address) not in LOOPBACK:
        raise RuntimeError(f"network access blocked in tests: {address}")
    return _real_connect(self, address)


def _guarded_create_connection(address, *args, **kwargs):
    if _host_of(address) not in LOOPBACK:
        raise RuntimeError(f"network access blocked in tests: {address}")
    return _real_create_connection(address, *args, **kwargs)


HIDDEN = ("NVIDIA_API_KEY", "NVIDIA_NEMOTRON_API_KEY", "GEMINI_API_KEY", "HF_TOKEN", "LAYA_API_KEY",
          "COPILOT_PROFILE", "COPILOT_TODAY", "COPILOT_CHAT_PROVIDER", "LAYA_BASE_URL", "LAYA_MODEL",
          "COPILOT_ENV_FILE", "COPILOT_APIS_LIVE", "COPILOT_TOKENIZER", "LAYA_MODE", "COPILOT_DEBUG_NODES")
SAVED_ENV: dict[str, str | None] = {}


def pytest_configure(config):
    # Keys and env files from the developer machine never reach offline tests; live tests restore them.
    for name in HIDDEN:
        SAVED_ENV[name] = os.environ.get(name)
    for name in HIDDEN[:10]:
        os.environ.pop(name, None)
    os.environ["LAYA_MODE"] = "off"  # offline tests never load a Laya checkpoint; tests that need Laya fake it
    os.environ.pop("COPILOT_DEBUG_NODES", None)
    os.environ["COPILOT_ENV_FILE"] = str(ROOT / "tests" / "_no_env_file")
    os.environ["COPILOT_TODAY"] = "2026-10-06"
    os.environ["COPILOT_APIS_LIVE"] = "false"
    os.environ["COPILOT_TOKENIZER"] = "builtin"  # same token counts on every machine


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        if os.environ.get("COPILOT_LIVE_TESTS") != "1":
            pytest.skip("live test: set COPILOT_LIVE_TESTS=1 and real keys")
        for name, value in SAVED_ENV.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)
        if not SAVED_ENV.get("COPILOT_ENV_FILE"):
            monkeypatch.setenv("COPILOT_ENV_FILE", str(ROOT / ".env"))
        monkeypatch.setenv("COPILOT_APIS_LIVE", "true")
        return
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    path = tmp_path / "runs"
    monkeypatch.setenv("COPILOT_RUNS_DIR", str(path))
    return path


@pytest.fixture(scope="session")
def pack_kb(tmp_path_factory):
    """The pack's own sources ingested once, offline, into a session-wide runs folder."""
    from campus_copilot import config
    from campus_copilot.ingest import pipeline

    path = tmp_path_factory.mktemp("pack") / "runs"
    previous = os.environ.get("COPILOT_RUNS_DIR")
    os.environ["COPILOT_RUNS_DIR"] = str(path)
    try:
        settings = config.get_settings("offline", {"ingest.sources": ["data/sources"]})
        state = pipeline.run_ingest(settings, store="all", echo=lambda _: None)
        assert state["stages"]["verify"]["stats"]["passed"]
    finally:
        if previous is None:
            os.environ.pop("COPILOT_RUNS_DIR", None)
        else:
            os.environ["COPILOT_RUNS_DIR"] = previous
    return path


@pytest.fixture
def pack_env(pack_kb, tmp_path, monkeypatch):
    """Point the app at the session knowledge base, with a private copy so writes never leak between tests."""
    import shutil

    runs = tmp_path / "runs"
    shutil.copytree(pack_kb, runs)
    monkeypatch.setenv("COPILOT_RUNS_DIR", str(runs))
    return runs


@pytest.fixture(scope="session")
def adversarial_kb(pack_kb, tmp_path_factory):
    """The pack knowledge base plus the poisoned E13 document."""
    import shutil

    from campus_copilot import config
    from campus_copilot.ingest import pipeline

    path = tmp_path_factory.mktemp("adversarial") / "runs"
    shutil.copytree(pack_kb, path)
    previous = os.environ.get("COPILOT_RUNS_DIR")
    os.environ["COPILOT_RUNS_DIR"] = str(path)
    try:
        settings = config.get_settings("e13_attacks", {"app.force_offline": True,
                                                       "ingest.sources": ["data/sources"]})
        state = pipeline.run_ingest(settings, echo=lambda _: None)
        assert "adversarial-fines-notice" in state["stages"]["store"]["stats"]["documents_processed"]
    finally:
        if previous is None:
            os.environ.pop("COPILOT_RUNS_DIR", None)
        else:
            os.environ["COPILOT_RUNS_DIR"] = previous
    return path


@pytest.fixture
def adversarial_env(adversarial_kb, tmp_path, monkeypatch):
    import shutil

    runs = tmp_path / "runs"
    shutil.copytree(adversarial_kb, runs)
    monkeypatch.setenv("COPILOT_RUNS_DIR", str(runs))
    return runs
