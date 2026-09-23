"""Build-path checkpoints: shared helpers. Each checkpoint runs offline on a copy of the pack's sources."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from campus_copilot import config
from campus_copilot.ingest import pipeline


@pytest.fixture
def pack_sources(tmp_path, runs_dir) -> Path:
    folder = tmp_path / "sources"
    shutil.copytree(config.DATA_DIR / "sources", folder, ignore=shutil.ignore_patterns("_src"))
    return folder


def step_settings(step: int, sources: list[Path], **extra):
    overrides = {"ingest.sources": [str(p) for p in sources], **extra}
    return config.get_settings(config.step_profile_name(step), {"app.force_offline": True, "apis.live": False,
                                                                  **overrides})


def ingest(settings, **kwargs) -> dict:
    return pipeline.run_ingest(settings, echo=lambda _: None, **kwargs)


def artifact(state: dict, stage: str):
    path = pipeline.ingest_root() / state["run_id"] / pipeline.ARTIFACTS[stage]
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def offline_copilot(step: int | None, **overrides):
    """A Copilot for one build step (or the baseline), offline, with the demo clock."""
    from campus_copilot.graph.build import Copilot
    from campus_copilot.graph.demo import demo_settings

    profile = config.step_profile_name(step) if step else "baseline"
    return Copilot(demo_settings(profile, {"app.force_offline": True, "apis.live": False, **overrides}))


def demo_board(step: int | None, **overrides):
    from campus_copilot.graph.demo import run_demo

    copilot = offline_copilot(step, **overrides)
    try:
        return run_demo(copilot), copilot
    finally:
        copilot.close()


def spans(copilot, board, name: str) -> list[dict]:
    out = []
    for outcome in board.outcomes:
        out += [s for s in copilot.trace(outcome.result.trace_id) if s["span"] == name]
    return out
