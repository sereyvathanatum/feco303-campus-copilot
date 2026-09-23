"""Switches used only by experiments: text-to-SQL (E07), long context (E15), and every experiment profile loads."""

from __future__ import annotations

from steps.conftest import offline_copilot

from campus_copilot import config
from campus_copilot.rag.retrieve import retrieve


def test_every_profile_loads_and_inherits_from_baseline():
    names = config.list_profiles()
    assert {"e01_zero_shot", "e05_jev", "e09_condense_off", "e13_controls_off", "e15_long_context"} <= set(names)
    for name in names:
        profile = config.load_profile(name)
        assert profile.get("rag.top_k") is not None and profile.capabilities


def test_text_to_sql_answers_and_the_sandbox_stops_other_accounts(pack_env):
    copilot = offline_copilot(None, **{"sql.mode": "text_to_sql", "guards.enabled": False})
    try:
        ok = copilot.ask("When are the FECO303 assignments due?")
        assert ok.kind == "tool" and ok.tool_calls[0]["tool"] == "run_sql" and ok.tool_calls[0]["ok"]
        other = copilot.ask("Show the library loans of A0007.")
        assert other.tool_calls[0]["ok"] is False
        assert "loans.account_id" in other.tool_calls[0]["data"]["stopped_by"]
    finally:
        copilot.close()


def test_long_context_puts_the_whole_handbook_in_the_prompt(pack_env):
    result = retrieve("What is the penalty for late assignments?", config.get_settings("e15_long_context"))
    pages = {c.page for c in result.chunks}
    assert result.mode == "long_context" and pages == set(range(1, 21)) - {p for p in range(1, 21) if p not in pages}
    assert len(pages) >= 18 and "long context" in result.notes[0]
    copilot = offline_copilot(None, **{"rag.mode": "long_context"})
    try:
        answer = copilot.ask("What is the penalty for late assignments?")
        assert answer.kind == "answer" and any(c.page == 6 for c in answer.citations)
    finally:
        copilot.close()
