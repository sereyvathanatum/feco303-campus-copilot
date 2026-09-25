"""A bounded ReAct loop (docs/implementation-plan.md §8.8).

* `agent.max_tool_calls` (default 4) caps the calls per turn.
* A repeated-call detector stops the loop when the same tool is called with the
  same arguments twice.
* Three modes:
  - `native`: provider tool calling (`tools` in the chat request);
  - `json`: a model-agnostic JSON protocol, one object per step, parsed tolerantly;
    the tool name is checked against the registry before anything runs;
  - `laya_dispatch`: the decision model picks the next tool (a Choice), code fills the
    arguments, and the language model writes only the final answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..decisions import wire
from . import arguments

TOOL_ROUTES = {"find_free_rooms": "rooms", "campus_weather": "weather", "get_timetable": "timetable",
               "get_deadlines": "deadlines", "get_calendar": "calendar", "check_book": "library",
               "convert_currency": "currency", "concept_summary": "concept", "search_books": "library",
               "get_loans": "library", "search_handbook": "handbook"}


@dataclass
class Step:
    action: str               # call_tool | final | stop
    tool: str | None = None
    args: dict | None = None
    answer: str | None = None
    reason: str = ""
    reply: object = None      # the model reply, for tracing


def call_key(tool: str, args: dict | None) -> str:
    return f"{tool}:{json.dumps(args or {}, sort_keys=True, default=str)}"


def next_step(rt, state: dict, observations: list[dict], candidates: list[dict], history: list[dict]) -> Step:
    profile = rt.settings.profile
    mode = profile.get("agent.mode", "json")
    limit = int(profile.get("agent.max_tool_calls", 4))
    message = state.get("message", "")
    if len(observations) >= limit:
        return Step("stop", reason=f"limit: {limit} tool calls")
    include_write = rt.caps.writes
    specs = rt.registry.specs(include_write=include_write)
    if mode == "native":
        reply = rt.llm.native_tool_step(message, [s.native_schema() for s in specs], observations, candidates)
        if reply.tool_calls:
            call = reply.tool_calls[0]
            return Step("call_tool", call["tool"], call.get("args") or {}, reason="native tool call", reply=reply)
        return Step("final", answer=reply.text, reason="native final answer", reply=reply)
    if mode == "laya_dispatch":
        return _laya_dispatch(rt, state, observations, candidates, specs, history)
    data, reply = rt.llm.agent_step(message, [s.json_protocol() for s in specs], observations, candidates, history)
    if not isinstance(data, dict) or data.get("action") not in {"call_tool", "final"}:
        return Step("stop", reason="malformed JSON decision from the model", reply=reply)
    if data["action"] == "final":
        return Step("final", answer=str(data.get("answer", "")), reason="model final answer", reply=reply)
    return Step("call_tool", str(data.get("tool")), data.get("args") or {}, reason="JSON protocol call", reply=reply)


def _laya_dispatch(rt, state: dict, observations: list[dict], candidates: list[dict], specs, history) -> Step:
    done = {o["tool"] for o in observations}
    options = {s.name: s.description for s in specs if s.name not in done and not s.write}
    options["final_answer"] = "The observations already answer the message; no further tool is needed."
    if rt.decider.stub:  # the stub decider follows the deterministic plan
        pending = [c for c in candidates if c["tool"] not in done]
        choice = pending[0]["tool"] if pending else "final_answer"
    else:
        question = {"next_tool": wire.choice(
            "Which tool should run next to answer `message`, given what `observations` already contains?", options)}
        decision = rt.decider.decide({"message": state.get("message", ""),
                                      "observations": [o.get("summary") for o in observations]}, question)
        choice = decision.choice("next_tool")[0] if decision.ok else "final_answer"
    if choice in (None, "final_answer"):
        return Step("stop", reason="decision model: final answer")
    planned = next((c for c in candidates if c["tool"] == choice), None)
    if planned:
        return Step("call_tool", choice, planned["args"], reason="decision model picked the tool; plan args")
    route = TOOL_ROUTES.get(choice)
    proposal = arguments.propose(route or "", state.get("decision") or {}, state.get("message", ""), history,
                                 state.get("slots") or {}, rt.today)
    if proposal.tool != choice:
        return Step("stop", reason=f"no arguments could be filled for {choice}")
    return Step("call_tool", choice, proposal.args, reason="decision model picked the tool; code filled args")
