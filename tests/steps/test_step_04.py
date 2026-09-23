"""Step 4 checkpoint: embed, store, and verify."""

import pytest

from .conftest import artifact, ingest, step_settings

pytestmark = pytest.mark.step04


def test_probes_pass_and_reingest_is_incremental(pack_sources):
    settings = step_settings(4, [pack_sources])
    first = ingest(settings)
    verify = first["stages"]["verify"]["stats"]
    assert verify["passed"], verify["failing_probes"]
    assert verify["k"] == 3
    second = ingest(settings)
    assert second["stages"]["embed"]["stats"]["calls"] == 0
    doc = pack_sources / "topic-agents.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "\n## Budgets\n\nEach loop also has a token budget per turn.\n",
                   encoding="utf-8")
    third = ingest(settings)
    changed = [c for c in artifact(third, "chunk") if c["source_id"] == "topic-agents"]
    embedded = third["stages"]["embed"]["stats"]["embedded"]
    assert third["stages"]["gather"]["stats"]["by_status"]["changed"] == 1
    assert 0 < embedded <= len(changed)
