"""Step 1 checkpoint: gather sources."""

import shutil
from pathlib import Path

import pytest

from .conftest import artifact, ingest, step_settings

pytestmark = pytest.mark.step01
FIXTURE_PDF = Path(__file__).parents[1] / "fixtures" / "ingest" / "fixture-rules.pdf"


def test_every_pack_document_is_listed_with_its_hash(pack_sources):
    state = ingest(step_settings(1, [pack_sources]))
    assert state["stages"]["extract"]["status"].startswith("skipped")
    docs = artifact(state, "gather")
    expected = {p.name for p in pack_sources.iterdir() if p.suffix in {".pdf", ".md"}}
    assert {Path(d["file"]).name for d in docs} == expected
    assert all(len(d["sha256"]) == 64 for d in docs)


def test_added_pdf_is_new_and_missing_licence_is_flagged(pack_sources, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    shutil.copyfile(FIXTURE_PDF, inbox / "dropped-notice.pdf")
    state = ingest(step_settings(1, [pack_sources, inbox]))
    dropped = [d for d in artifact(state, "gather") if d["source_id"] == "dropped-notice"][0]
    assert dropped["status"] == "new"
    assert "licence unknown" in dropped["flags"]
