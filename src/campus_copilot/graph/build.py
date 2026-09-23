"""`StateGraph` wiring driven by the active capabilities, plus the `Copilot` entry point.

The checkpointer is a `SqliteSaver` in `runs/memory.db`, keyed by `thread_id`. With
the `memory` capability off, every turn starts a fresh thread. Write actions stop
at an `interrupt()` in the `confirm` node and resume with `Copilot.resume`.
"""

from __future__ import annotations

import sqlite3
import uuid

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .. import config
from ..schemas import TurnResult
from .nodes import Nodes, Runtime, new_trace_id
from .state import CopilotState

FIXED = ("clarify", "refuse", "handoff", "abstain")


def build_graph(rt: Runtime, checkpointer=None):
    caps = rt.caps
    nodes = Nodes(rt)
    g = StateGraph(CopilotState)
    g.add_node("begin", nodes.begin)
    g.add_node("respond", nodes.respond)
    g.add_edge(START, "begin")
    g.add_edge("respond", END)

    if not caps.rag:
        g.add_node("status", nodes.status)
        g.add_edge("begin", "status")
        g.add_edge("status", "respond")
        return g.compile(checkpointer=checkpointer)

    g.add_node("rag_answer", nodes.rag_answer)
    if caps.guards and rt.profile.get("rag.answer_check", True) and caps.decisions:
        g.add_node("verify_answer", nodes.verify_answer)
        g.add_edge("rag_answer", "verify_answer")
        g.add_edge("verify_answer", "respond")
    else:
        g.add_edge("rag_answer", "respond")
    rag_entry = "rag_answer"
    if caps.memory:
        g.add_node("condense_query", nodes.condense_query)
        g.add_edge("condense_query", "rag_answer")
        rag_entry = "condense_query"

    if not caps.decisions:
        g.add_edge("begin", rag_entry)  # without decisions, every message takes the RAG path
        return g.compile(checkpointer=checkpointer)

    first = "guard_and_route"
    if caps.vision:
        g.add_node("read_image", nodes.read_image)
        g.add_conditional_edges("begin", lambda s: "read_image" if s.get("image_path") else "guard_and_route",
                                ["read_image", "guard_and_route"])
        g.add_edge("read_image", "guard_and_route")
    else:
        g.add_edge("begin", first)
    g.add_node("guard_and_route", nodes.guard_and_route)
    g.add_node("apply_policy", nodes.apply_policy)
    g.add_edge("guard_and_route", "apply_policy")
    for kind in FIXED:
        g.add_node(kind, nodes.fixed_reply)
        g.add_edge(kind, "respond")
    g.add_node("small_reply", nodes.small_reply)
    g.add_edge("small_reply", "respond")

    targets = {"rag": rag_entry, "small": "small_reply", **{k: k for k in FIXED}}
    if caps.tools:
        g.add_node("single_tool", nodes.single_tool)
        targets["tool"] = "single_tool"
    if caps.agent:
        g.add_node("agent_reason", nodes.agent_reason)
        g.add_node("agent_act", nodes.agent_act)
        targets["agent"] = "agent_reason"
        g.add_edge("agent_act", "agent_reason")
    g.add_conditional_edges("apply_policy", lambda s: targets.get(s.get("action") or "", "abstain"),
                            sorted(set(targets.values())))

    write_path = caps.writes
    if write_path:
        g.add_node("risk_gate", nodes.risk_gate)
        g.add_node("confirm", nodes.confirm)
        g.add_conditional_edges("risk_gate", lambda s: "confirm" if s.get("pending_write") else "respond",
                                ["confirm", "respond"])
        g.add_edge("confirm", "respond")
    if caps.tools:
        tool_next = ["respond"] + (["risk_gate"] if write_path else [])
        g.add_conditional_edges("single_tool", lambda s: "risk_gate" if write_path and s.get("pending_write")
                                else "respond", tool_next)
    if caps.agent:
        agent_next = ["agent_act", "respond"] + (["risk_gate"] if write_path else [])

        def after_reason(state):
            if write_path and state.get("pending_write"):
                return "risk_gate"
            return "agent_act" if state.get("pending_call") else "respond"

        g.add_conditional_edges("agent_reason", after_reason, agent_next)
    return g.compile(checkpointer=checkpointer)


class Copilot:
    """One chatbot instance for one profile: `ask` a turn, `resume` a pending write, read a thread's history."""

    def __init__(self, settings=None, profile: str | None = None, **services) -> None:
        self.settings = settings or config.get_settings(profile)
        self.rt = Runtime(self.settings, **services)
        path = config.runs_dir() / "memory.db"
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self.checkpointer = SqliteSaver(self._conn)
        self.checkpointer.setup()
        self.graph = build_graph(self.rt, self.checkpointer)

    @property
    def caps(self):
        return self.rt.caps

    def _thread(self, thread_id: str | None) -> str:
        if not self.caps.memory or not thread_id:
            return uuid.uuid4().hex[:10]  # without memory every turn starts a fresh thread
        return thread_id

    def ask(self, message: str, thread_id: str | None = None, account_id: str | None = None,
            image_path: str | None = None) -> TurnResult:
        thread = self._thread(thread_id)
        trace_id = new_trace_id()
        account = account_id or self.settings.profile.get("app.account_id", "A0001")
        payload = {"messages": [HumanMessage(message)], "message": message, "account_id": account,
                   "image_path": image_path if self.caps.vision else None, "trace_id": trace_id}
        cfg = {"configurable": {"thread_id": thread}}
        with self.rt.tracer(trace_id).span("turn", thread_id=thread, message=message[:200]):
            self.graph.invoke(payload, cfg)
        return self._result(thread, trace_id)

    def resume(self, thread_id: str, confirm: bool) -> TurnResult:
        cfg = {"configurable": {"thread_id": thread_id}}
        state = self.graph.get_state(cfg)
        if not state.next:
            return TurnResult(kind="error", answer="No pending action in this thread.", thread_id=thread_id)
        trace_id = state.values.get("trace_id") or new_trace_id()
        with self.rt.tracer(trace_id).span("resume", confirm=confirm):
            self.graph.invoke(Command(resume={"confirm": confirm}), cfg)
        return self._result(thread_id, trace_id)

    def pending(self, thread_id: str) -> dict | None:
        state = self.graph.get_state({"configurable": {"thread_id": thread_id}})
        return state.values.get("pending_write") if state.next else None

    def _result(self, thread: str, trace_id: str) -> TurnResult:
        state = self.graph.get_state({"configurable": {"thread_id": thread}})
        data = dict(state.values.get("result") or {"kind": "error", "answer": "No result."})
        data["thread_id"] = thread
        data["trace_id"] = trace_id
        return TurnResult.model_validate(data)

    def trace(self, trace_id: str) -> list[dict]:
        tracer = self.rt.tracers.get(trace_id)
        return tracer.timeline() if tracer else []

    def history(self, thread_id: str) -> list:
        state = self.graph.get_state({"configurable": {"thread_id": thread_id}})
        return list(state.values.get("messages") or [])

    def state(self, thread_id: str) -> dict:
        return dict(self.graph.get_state({"configurable": {"thread_id": thread_id}}).values)

    def mermaid(self) -> str:
        return self.graph.get_graph().draw_mermaid()

    def close(self) -> None:
        transport = getattr(self.rt, "transport", None)
        if hasattr(transport, "close"):
            transport.close()
        self._conn.close()
