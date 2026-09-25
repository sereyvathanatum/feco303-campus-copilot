"""Live checks (`pytest -m live`), skipped unless COPILOT_LIVE_TESTS=1 and real keys are in `.env`.

One chat call, one embedding call, one image call, the Laya reference call, and one call per public API.
Run before each release and at term start.
"""

from __future__ import annotations

import datetime as dt

import pytest

from campus_copilot import config

pytestmark = pytest.mark.live


def live_settings():
    return config.get_settings("baseline", {"apis.live": True})


def test_chat_model_answers():
    from campus_copilot.llm.client import get_llm

    settings = live_settings()
    if not settings.has_live_llm:
        pytest.skip("no NIM or Gemini key")
    reply = get_llm(settings).small_reply("Hello")
    assert not reply.stub, reply.notes
    assert reply.text.strip()


def test_nim_embeddings_passage_and_query():
    from campus_copilot.rag.embeddings import NimEmbedder, get_embedder

    settings = live_settings()
    if not settings.has_nim:
        pytest.skip("no NIM key")
    embedder = get_embedder(settings)
    assert isinstance(embedder, NimEmbedder)
    passage = embedder.embed_documents(["Late assignments lose 10 percent per day."])[0]
    query = embedder.embed_query("late assignment penalty")
    assert len(passage) == len(query) > 100
    assert embedder.stats.input_types == ["passage", "query"]


def test_vision_model_reads_the_clean_poster():
    from campus_copilot.llm.client import get_llm

    settings = live_settings()
    if not settings.has_live_llm:
        pytest.skip("no NIM or Gemini key")
    data, reply = get_llm(settings).read_image(str(config.DATA_DIR / "images" / "poster_clean.png"), "2026-10-06")
    assert not reply.stub, reply.notes
    assert "A-101" in (data.get("transcription") or "") + str(data.get("event"))


def test_laya_reference_call():
    from campus_copilot.decisions.laya import smoke

    settings = live_settings()
    if not settings.has_laya:
        pytest.skip("Laya unavailable: pip install laya, or LAYA_MODE=http with laya-serve running")
    decision, info = smoke(settings)
    assert decision.ok, decision.error
    assert 0.0 <= decision.noul("urgency") <= 1.0
    assert decision.model.startswith("laya/")


@pytest.mark.parametrize("name,args", [
    ("campus_weather", {"date": "today"}),
    ("convert_currency", {"amount": 20, "direction": "usd_to_khr"}),
    ("search_books", {"query": "machine learning"}),
    ("concept_summary", {"topic": "attention"}),
])
def test_public_api(name, args, tmp_path, monkeypatch):
    from campus_copilot.tools.http import HttpClient
    from campus_copilot.tools.registry import ToolContext, registry

    monkeypatch.setenv("COPILOT_RUNS_DIR", str(tmp_path))
    monkeypatch.setenv("COPILOT_TODAY", dt.date.today().isoformat())
    settings = config.get_settings("baseline", {"apis.live": True, "app.force_offline": False})
    ctx = ToolContext.create(settings, "A0001", http=HttpClient(settings, live=True))
    result = registry().run(name, args, ctx)
    assert result["ok"], result.get("error")
    assert result["source"] in {"live", "cache"} and result["attribution"]
