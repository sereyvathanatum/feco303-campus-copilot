"""Step 3 checkpoint: clean and chunk."""

import pytest

from .conftest import artifact, ingest, step_settings

pytestmark = pytest.mark.step03


def test_noise_gone_pages_respected_sections_present(pack_sources):
    state = ingest(step_settings(3, [pack_sources]))
    cleaned = {(u["source_id"], u["page"]): u["text"] for u in artifact(state, "clean")}
    info_text = "\n".join(t for (sid, _), t in cleaned.items() if sid == "academic-info")
    # the converter left one HTML comment per dropped image; cleaning removes them
    assert "<!-- image -->" not in info_text
    assert state["stages"]["clean"]["stats"]["removed"]["html_comments"] > 0
    chunks = artifact(state, "chunk")
    for c in chunks:
        if c["page"]:
            assert c["text"] in cleaned[(c["source_id"], c["page"])], "a PDF chunk crosses a page boundary"
    md = [c for c in chunks if c["source_id"] == "academic-info"]
    assert md and all(c["section"] for c in md)  # every Markdown chunk carries its heading
    assert any("\u203a" in c["section"] for c in md)  # nested headings become a breadcrumb
    report = state["stages"]["chunk"]["stats"]
    assert "over_window" in report and report["embed_window"] > 0
