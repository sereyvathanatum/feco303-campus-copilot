"""Step 2 checkpoint: extract text from PDF and Markdown."""

import pytest
from pypdf import PdfReader

from .conftest import artifact, ingest, step_settings

pytestmark = pytest.mark.step02


def test_page_count_image_pages_flagged_and_markdown_unit(pack_sources):
    state = ingest(step_settings(2, [pack_sources]))
    units = artifact(state, "extract")
    prospectus = [u for u in units if u["source_id"] == "camtech-prospectus"]
    assert len(prospectus) == len(PdfReader(str(pack_sources / "CamTech-Prospectus.pdf")).pages)
    assert [u["page"] for u in prospectus] == list(range(1, len(prospectus) + 1))
    # the prospectus is a designed brochure: several pages carry an image and no text layer
    empty = [u for u in prospectus if not u["text"].strip()]
    assert empty and all(any("empty or near-empty page" in f for f in u["flags"]) for u in empty)
    info = [u for u in units if u["source_id"] == "academic-info"]
    assert len(info) == 1 and info[0]["page"] is None  # one Markdown file, no page numbers
    assert not info[0]["text"].startswith("---")
