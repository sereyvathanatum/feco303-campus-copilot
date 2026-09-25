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
    doc = pack_sources / "Academic_Info.md"
    doc.write_text(doc.read_text(encoding="utf-8")
                   + "\n## IX. Late payment\n\nA term fee paid after the deadline carries a 5 percent surcharge.\n",
                   encoding="utf-8")
    third = ingest(settings)
    changed = [c for c in artifact(third, "chunk") if c["source_id"] == "academic-info"]
    embedded = third["stages"]["embed"]["stats"]["embedded"]
    assert third["stages"]["gather"]["stats"]["by_status"]["changed"] == 1
    assert 0 < embedded <= len(changed)
