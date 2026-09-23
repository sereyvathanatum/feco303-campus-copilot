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
