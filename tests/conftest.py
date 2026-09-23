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


def pytest_configure(config):
    # Keys and env files from the developer machine never reach tests.
    for name in ("NVIDIA_API_KEY", "TYPESAFE_API_KEY", "COPILOT_PROFILE", "COPILOT_TODAY"):
        os.environ.pop(name, None)
    os.environ["COPILOT_ENV_FILE"] = str(ROOT / "tests" / "_no_env_file")
    os.environ["COPILOT_TODAY"] = "2026-10-06"
    os.environ["COPILOT_APIS_LIVE"] = "false"
    os.environ["COPILOT_TOKENIZER"] = "builtin"  # same token counts on every machine


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        if os.environ.get("COPILOT_LIVE_TESTS") != "1":
            pytest.skip("live test: set COPILOT_LIVE_TESTS=1 and real keys")
        return
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket, "create_connection", _guarded_create_connection)


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    path = tmp_path / "runs"
    monkeypatch.setenv("COPILOT_RUNS_DIR", str(path))
    return path
