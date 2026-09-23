"""Step 3 checkpoint: clean and chunk."""

import pytest

from .conftest import artifact, ingest, step_settings

pytestmark = pytest.mark.step03


def test_headers_gone_pages_respected_sections_present(pack_sources):
    state = ingest(step_settings(3, [pack_sources]))
    cleaned = {(u["source_id"], u["page"]): u["text"] for u in artifact(state, "clean")}
    handbook_text = "\n".join(t for (sid, _), t in cleaned.items() if sid == "campus-handbook")
    assert "(demo edition)" not in handbook_text.replace("CamTech Campus Handbook 2026-2027\n", "")
    assert "Page 3 of" not in handbook_text
    chunks = artifact(state, "chunk")
    for c in chunks:
        if c["page"]:
            assert c["text"] in cleaned[(c["source_id"], c["page"])], "a PDF chunk crosses a page boundary"
    md = [c for c in chunks if c["source_id"] == "campus-services-faq"]
    assert md and all("\u203a" in c["section"] for c in md)
    report = state["stages"]["chunk"]["stats"]
    assert "over_window" in report and report["embed_window"] > 0
