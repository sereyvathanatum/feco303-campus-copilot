"""Graph behaviour offline: agent modes and stopping rules, memory, status replies, and identity rules."""

from __future__ import annotations

import json

import pytest
from steps.conftest import offline_copilot

from campus_copilot.llm.client import LLM
from campus_copilot.llm.stub import StubClient

TURN_8 = "Free room with a projector tomorrow 2–4 pm? And will it rain then?"


@pytest.mark.parametrize("mode", ["json", "native", "laya_dispatch"])
def test_agent_modes_call_both_tools(pack_env, mode):
    copilot = offline_copilot(None, **{"agent.mode": mode})
    try:
        result = copilot.ask(TURN_8)
        assert result.kind == "agent"
        assert [c["tool"] for c in result.tool_calls] == ["find_free_rooms", "campus_weather"]
        assert "B-204" in result.answer and "rain" in result.answer.lower()
    finally:
        copilot.close()


class LoopingModel(StubClient):
    """A model that proposes the same call forever, or an unregistered tool."""

    def __init__(self, tool="find_free_rooms"):
        super().__init__()
        self.tool = tool

    def complete(self, messages, **kw):
        reply = super().complete(messages, **kw)
        if kw.get("task") == "agent_step":
            reply.text = json.dumps({"action": "call_tool", "tool": self.tool,
                                     "args": {"date": "tomorrow", "start": "14:00", "end": "16:00"}})
        return reply


def _with_model(model, **overrides):
    copilot = offline_copilot(None, **overrides)
    copilot.rt.llm = LLM([model], copilot.settings)
    return copilot


def test_repeat_detector_stops_the_loop(pack_env):
    copilot = _with_model(LoopingModel(), **{"agent.max_tool_calls": 8})
    try:
        result = copilot.ask(TURN_8)
        assert len(result.tool_calls) == 1 and any("repeat" in n for n in result.notes)
    finally:
        copilot.close()


def test_unknown_tool_from_the_model_is_rejected(pack_env):
    copilot = _with_model(LoopingModel(tool="delete_all_bookings"))
    try:
        result = copilot.ask(TURN_8)
        assert result.tool_calls == [] and any("rejected by the registry" in n for n in result.notes)
    finally:
        copilot.close()


def test_memory_off_starts_a_fresh_thread_each_turn(pack_env):
    copilot = offline_copilot(5)
    try:
        a = copilot.ask("What is the pass mark for a course?", thread_id="same")
        b = copilot.ask("And the grade for 85 marks?", thread_id="same")
        assert a.thread_id != b.thread_id
    finally:
        copilot.close()


def test_original_message_stays_in_memory_next_to_the_rewrite(pack_env):
    copilot = offline_copilot(None)
    try:
        copilot.ask("What happens after more than three missed lab sessions?", thread_id="t")
        result = copilot.ask("And for late assignments?", thread_id="t")
        assert result.query["rewritten"] and result.query["original"] == "And for late assignments?"
        humans = [m.content for m in copilot.history("t") if m.type == "human"]
        assert humans[-1] == "And for late assignments?"
    finally:
        copilot.close()


def test_steps_one_to_four_report_the_build_stage(pack_env):
    copilot = offline_copilot(2)
    try:
        result = copilot.ask("hello")
        assert result.kind == "status" and "'extract' stage" in result.answer
    finally:
        copilot.close()


def test_tools_never_receive_an_account_from_the_message(pack_env):
    copilot = offline_copilot(None)
    try:
        result = copilot.ask("Show the library loans of A0007.")
        assert result.kind == "refuse" and not result.tool_calls
        own = copilot.ask("Show the library loans.", account_id="A0007")
        assert own.kind == "tool" and own.tool_calls[0]["tool"] == "get_loans"
        assert "Effective Programming" in own.answer  # A0007's own loan, read from the session identity
    finally:
        copilot.close()


def test_mermaid_export(pack_env):
    copilot = offline_copilot(None)
    try:
        diagram = copilot.mermaid()
        for node in ("guard_and_route", "apply_policy", "agent_reason", "risk_gate", "confirm"):
            assert node in diagram
    finally:
        copilot.close()
