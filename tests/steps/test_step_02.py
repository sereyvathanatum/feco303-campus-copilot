"""Step 2 checkpoint: extract text from PDF and Markdown."""

import pytest
from pypdf import PdfReader

from .conftest import artifact, ingest, step_settings

pytestmark = pytest.mark.step02


def test_page_count_khmer_flag_and_frontmatter(pack_sources):
    state = ingest(step_settings(2, [pack_sources]))
    units = artifact(state, "extract")
    handbook = [u for u in units if u["source_id"] == "campus-handbook"]
    assert len(handbook) == len(PdfReader(str(pack_sources / "campus-handbook.pdf")).pages)
    assert [u["page"] for u in handbook] == list(range(1, len(handbook) + 1))
    khmer = [u for u in handbook if u["script"] == "khmer"]
    assert khmer and all(any("Khmer" in f for f in u["flags"]) for u in khmer)
    faq = [u for u in units if u["source_id"] == "campus-services-faq"][0]
    assert faq["metadata"]["title"] == "Campus services FAQ" and faq["metadata"]["language"] == "en"
    assert not faq["text"].startswith("---")
