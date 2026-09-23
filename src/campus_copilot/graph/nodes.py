"""Graph nodes (docs/implementation-plan.md §5.1, §8.8) and the runtime services they share.

Every node opens a trace span. Nodes return partial state updates; nothing that
cannot be serialised is kept in state, so the checkpointer can persist every turn.
"""

from __future__ import annotations

import re
import uuid

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from .. import config
from ..db import connection, queries
from ..decisions import policy, questions as qcat
from ..decisions.base import Decision, get_decider
from ..decisions.stub import StubDecider
from ..ingest import store as kb
from ..llm import prompts
from ..llm.client import get_llm
from ..observability.trace import Tracer
from ..rag import condense as condense_mod
from ..rag.answer import answer as grounded_answer
from ..rag.embeddings import get_embedder
from ..rag.retrieve import retrieve
from ..schemas import ABSTAIN_TEXT, Citation, TurnResult
from ..textutil import sentences
from ..tools.http import HttpClient
from ..tools.registry import ToolContext, registry
from . import agent as agent_mod
from . import arguments
from .capabilities import Capabilities
from .memory import jev_history, model_window

SQL_ROUTES = {"timetable", "deadlines", "rooms", "library", "calendar"}
PER_TURN_RESET = {"decision": None, "route": None, "action": None, "query": {}, "tool_calls": [],
                  "pending_write": None, "pending_call": None, "sources": [], "answer": "", "result": None,
                  "flags": [], "notes": [],
                  "image_text": None, "image_reading": None}


class Runtime:
    """Services shared by the nodes of one compiled graph."""

    def __init__(self, settings, *, llm=None, small_llm=None, decider=None, http=None, db_path=None,
                 transport=None) -> None:
        self.settings = settings
        self.profile = settings.profile
        self.caps = Capabilities.from_profile(settings.profile)
        self.llm = llm or get_llm(settings, "chat")
        self.small_llm = small_llm or get_llm(settings, "small")
        self.decider = decider or get_decider(settings)
        self.registry = registry()
        self.kb_conn = kb.connect()
        self.embedder = get_embedder(settings)
        self.http = http or HttpClient(settings)
        self.db_path = connection.ensure_seeded(db_path)
        self.thresholds = policy.Thresholds.from_profile(settings.profile)
        self.today = config.today(settings.profile)
        self.courses = queries.course_codes(connection.read_connection(self.db_path))
        self.catalogue = qcat.turn_catalogue(self.courses)
        self.tracers: dict[str, Tracer] = {}
        self.transport = transport or self._transport()

    def _transport(self):
        if self.profile.get("tools.transport", "inprocess") == "mcp" and self.caps.mcp:
            try:
                from ..mcp.client import MCPTransport

                return MCPTransport(self)
            except Exception as exc:  # MCP unavailable: keep answering in-process and say so
                self.transport_note = f"MCP transport unavailable ({type(exc).__name__}: {exc}); in-process tools used"
        return InProcessTransport(self)

    def tracer(self, trace_id: str) -> Tracer:
        if trace_id not in self.tracers:
            self.tracers[trace_id] = Tracer(trace_id)
        return self.tracers[trace_id]

    def tool_ctx(self, account_id: str) -> ToolContext:
        ctx = ToolContext.create(self.settings, account_id, http=self.http, db_path=self.db_path)
        ctx.kb_conn, ctx.embedder, ctx.decider = self.kb_conn, self.embedder, self.decider
        return ctx

    def run_tool(self, name: str, args: dict, account_id: str, allow_write: bool = False) -> dict:
        spec = self.registry.get(name)
        if spec is not None and (spec.write or name == "run_sql"):  # writes and the SQL sandbox never travel over MCP
            return self.registry.run(name, args, self.tool_ctx(account_id), allow_write=allow_write)
        return self.transport.call(name, args, account_id)


class InProcessTransport:
    name = "inprocess"

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def call(self, name: str, args: dict, account_id: str) -> dict:
        return self.rt.registry.run(name, args, self.rt.tool_ctx(account_id))


def _history(state: dict) -> list:
    messages = state.get("messages") or []
    return messages[:-1] if messages and isinstance(messages[-1], HumanMessage) else messages


def _decision(state: dict) -> Decision | None:
    d = state.get("decision")
    return Decision(**{k: d[k] for k in ("ok", "answers", "decider", "model", "usage", "ms", "stub", "status", "error",
                                         "notes")}) if d else None


def _usage_delta(decider, before: dict) -> dict:
    after = dict(decider.usage_totals)
    return {"decider": decider.name, "decider_calls": after["calls"] - before["calls"],
            "tokens_in": after["input_tokens"] - before["input_tokens"],
            "tokens_out": after["output_tokens"] - before["output_tokens"], "stub": decider.stub or None}


def _format_tool_answer(result: dict) -> str:
    text = result.get("summary") or ("Done." if result.get("ok") else f"The lookup failed: {result.get('error')}")
    if result.get("attribution") and result["attribution"] not in text:
        text += f" Source: {result['attribution']}."
    return text


class Nodes:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    # ------------------------------------------------------------ helpers
    def span(self, state: dict, name: str, **attrs):
        return self.rt.tracer(state["trace_id"]).span(name, **attrs)

    def window(self, state: dict) -> list[dict]:
        if not self.rt.caps.memory:
            return []
        return model_window(_history(state), self.rt.settings).as_dicts()

    def screen_untrusted(self, state: dict, result: dict) -> tuple[dict, str | None]:
        """Tool-text filter: external text (for example Wikipedia) is checked for instructions aimed at the assistant."""
        rt = self.rt
        text = (result.get("data") or {}).get("extract") if isinstance(result.get("data"), dict) else None
        if not (result.get("untrusted") and text and rt.caps.guards and rt.profile.get("guards.enabled", True)):
            return result, None
        note = None
        with self.span(state, "screen_tool_text", tool=result.get("tool"), decider=rt.decider.name) as span:
            before = dict(rt.decider.usage_totals)
            verdict = rt.decider.judge_passages(state["message"], [text])[0]
            span.set(injection=verdict.get("injection"), **_usage_delta(rt.decider, before))
            if verdict.get("injection", 0.0) > float(rt.profile.get("policy.passage_injection", 0.70)):
                result = {**result, "data": {**result["data"], "extract": "[withheld]"}, "withheld": True,
                          "summary": (f"External source ({result.get('source_api', 'Wikipedia')}): the summary "
                                      "contained instructions aimed at the assistant and was withheld.")}
                note = f"untrusted tool text withheld: {result.get('tool')} (injection {verdict['injection']:.2f})"
        return result, note

    # -------------------------------------------------------------- nodes
    def begin(self, state: dict) -> dict:
        with self.span(state, "begin", account_id=state.get("account_id"), step=self.rt.profile.step) as span:
            window = model_window(_history(state), self.rt.settings)
            span.set(history_messages=len(_history(state)), window_messages=len(window.messages),
                     dropped_messages=window.dropped_messages, dropped_tokens=window.dropped_tokens)
            notes = [getattr(self.rt, "transport_note")] if getattr(self.rt, "transport_note", None) else []
            return {**PER_TURN_RESET, "turn": int(state.get("turn") or 0) + 1, "notes": notes,
                    "query": {"original": state.get("message", "")}}

    def status(self, state: dict) -> dict:
        """Steps 1-4: no chatbot yet; report how far the knowledge-base build has come."""
        with self.span(state, "status"):
            count = self.rt.kb_conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
            until = self.rt.profile.get("ingest.until", "verify")
            text = (f"No chatbot yet at this build step: the knowledge base is built up to the '{until}' stage "
                    f"({count} chunks stored). Run `python -m campus_copilot.cli ingest --until {until} --show {until}` "
                    "to inspect it.")
            return {"answer": text, "result": TurnResult(kind="status", answer=text).model_dump()}

    def read_image(self, state: dict) -> dict:
        with self.span(state, "read_image", image=state.get("image_path")) as span:
            from ..multimodal.notice_reader import read_notice

            reading = read_notice(self.rt, state["image_path"])
            span.record_llm(reading.pop("_reply", None))
            span.set(fields_flagged=reading.get("flagged"))
            return {"image_text": reading.get("transcription"), "image_reading": reading}

    def guard_and_route(self, state: dict) -> dict:
        with self.span(state, "guard_and_route") as span:
            conn = connection.read_connection(self.rt.db_path)
            account = state["account_id"]
            turn_state = qcat.turn_state(state["message"], jev_history(_history(state)), account,
                                         queries.enrolled_courses(conn, account), state.get("image_text"))
            decision = self.rt.decider.decide(turn_state, qcat.wire(self.rt.catalogue))
            notes = []
            if not decision.ok:
                notes.append(f"decider {self.rt.decider.name} failed ({decision.error}); stub decider used")
                decision = StubDecider().decide(turn_state, qcat.wire(self.rt.catalogue))
            span.set(decider=decision.decider, model=decision.model, decision=decision.answers,
                     tokens_in=decision.usage.get("input_tokens"), tokens_out=decision.usage.get("output_tokens"),
                     stub=decision.stub or None, decider_calls=1)
            route = decision.choice("route")[0]
            return {"decision": decision.as_dict(), "route": route, "notes": state.get("notes", []) + notes}

    def apply_policy(self, state: dict) -> dict:
        with self.span(state, "apply_policy") as span:
            decision = _decision(state)
            caps = self.rt.caps
            slots = state.get("slots") or {}
            has_slots = bool(slots.get("last_room_search")) and (decision.noul("wants_change", 0) or 0) >= 0.5
            if state.get("image_reading", {}) and (state.get("image_reading") or {}).get("event"):
                has_slots = True
            action = policy.decide_action(
                decision, self.rt.thresholds, guards_enabled=bool(self.rt.profile.get("guards.enabled", True)),
                tools=caps.tools, agent=caps.agent, offices=self.rt.profile.get("campus.offices", {}),
                has_slots=has_slots, force_agent=str(self.rt.profile.get("agent.force", "")),
                severity_check=caps.guards)
            span.set(action=action.kind, reason=action.reason, flags=action.flags or None)
            return {"action": action.kind, "route": action.route or state.get("route"),
                    "flags": action.flags, "answer": action.reply or "",
                    "notes": state.get("notes", []) + [f"policy: {action.reason}"]}

    def fixed_reply(self, state: dict) -> dict:
        """clarify, refuse, handoff, abstain: fixed texts from the policy (docs/implementation-plan.md §3.2)."""
        kind = state["action"]
        with self.span(state, kind):
            text = state.get("answer") or ABSTAIN_TEXT
            if kind == "abstain":
                text = ABSTAIN_TEXT
            return {"answer": text, "result": TurnResult(kind=kind, answer=text, route=state.get("route")).model_dump()}

    def small_reply(self, state: dict) -> dict:
        with self.span(state, "small_reply") as span:
            reply = self.rt.small_llm.small_reply(state["message"])
            span.record_llm(reply)
            return {"answer": reply.text, "result": TurnResult(kind="small_talk", answer=reply.text,
                                                               route="chit_chat").model_dump()}

    def condense_query(self, state: dict) -> dict:
        with self.span(state, "condense_query") as span:
            history = self.window(state)
            mode = self.rt.profile.get("rag.condense_query", "jev_gated")
            if not self.rt.caps.decisions and mode == "jev_gated":
                mode = "always"
            decision = _decision(state)
            follow = decision.noul("follow_up") if decision else None
            result = condense_mod.condense(state["message"], history, self.rt.small_llm, mode, state.get("route"),
                                           follow, self.rt.thresholds.follow_up)
            for reply in result.replies:
                span.record_llm(reply)
            span.set(**{"query.original": result.original, "query.rewritten": result.rewritten, "gate": result.reason,
                        "ran": result.ran})
            return {"query": result.as_dict()}

    def rag_answer(self, state: dict) -> dict:
        rt = self.rt
        with self.span(state, "rag_answer") as span:
            query = (state.get("query") or {}).get("rewritten") or state["message"]
            use_judge = rt.caps.guards and rt.profile.get("rag.passage_filter", True)
            with self.span(state, "retrieve", query=query) as rspan:
                result = retrieve(query, rt.settings, conn=rt.kb_conn, embedder=rt.embedder, decider=rt.decider)
                rspan.set(mode=result.mode, store=result.store, hits=[c.citation for c in result.chunks],
                          latency=result.latency_ms)
            chunks, dropped = result.chunks, []
            notes = list(result.notes)
            if use_judge and chunks and result.mode not in ("dense+judge", "long_context"):
                with self.span(state, "judge_passages", decider=rt.decider.name) as jspan:
                    before = dict(rt.decider.usage_totals)
                    verdicts = rt.decider.judge_passages(query, [c.text for c in chunks])
                    jspan.set(**_usage_delta(rt.decider, before))
                    keep = []
                    for chunk, verdict in zip(chunks, verdicts):
                        chunk.judge = verdict
                        if verdict.get("injection", 0) > float(rt.profile.get("policy.passage_injection", 0.70)):
                            dropped.append(chunk)
                            notes.append(f"passage filter dropped {chunk.citation}: instructions aimed at the assistant")
                        elif verdict.get("relevant", 1) < float(rt.profile.get("policy.passage_relevant", 0.45)):
                            dropped.append(chunk)
                        else:
                            keep.append(chunk)
                    chunks = keep
                    jspan.set(kept=[c.citation for c in keep], dropped=[c.citation for c in dropped])
            llm = rt.llm
            decision = _decision(state)
            if rt.profile.get("llm.model_routing", "off") == "jev_complexity" and decision:
                complexity = decision.score("complexity", 1.0) or 0.0
                if complexity < 0.7:
                    llm = rt.small_llm
                    notes.append(f"model routing: complexity {complexity:.2f} -> small model")
            answered = grounded_answer(query, chunks, llm, history=self.window(state), original=state["message"])
            for reply in answered.replies:
                span.record_llm(reply)
            notes += answered.notes
            kind = "abstain" if answered.grounded.abstained else "answer"
            sources = [c.as_dict() for c in result.chunks]
            span.set(kind=kind, citations=[c.render() for c in answered.grounded.citations])
            turn = TurnResult(kind=kind, answer=answered.text, route=state.get("route") or "handbook",
                              citations=answered.grounded.citations, sources=sources,
                              query=state.get("query") or {"original": state["message"]})
            return {"answer": answered.text, "sources": sources, "result": turn.model_dump(),
                    "notes": state.get("notes", []) + notes}

    def verify_answer(self, state: dict) -> dict:
        """Answer check: each answer sentence against its cited passage (claim_support); regenerate once, then abstain."""
        rt = self.rt
        result = state.get("result") or {}
        if result.get("kind") != "answer" or not result.get("citations"):
            return {}
        with self.span(state, "verify_answer", decider=rt.decider.name) as span:
            cited = {(c["source_id"], c.get("page"), c.get("section")) for c in result["citations"]}
            passages = [s["text"] for s in result.get("sources", [])
                        if (s["source_id"], s.get("page"), s.get("section") if not s.get("page") else None) in cited
                        or (s["source_id"], s.get("page"), None) in cited]
            claims = [s for s in sentences(re.sub(r"\[[^\]]+\]", "", result["answer"])) if len(s.split()) > 3]
            if not claims or not passages:
                return {}
            joined = "\n".join(passages)
            before = dict(rt.decider.usage_totals)
            verdicts = rt.decider.check_claims([(c, joined) for c in claims])
            span.set(**_usage_delta(rt.decider, before))
            threshold = float(rt.profile.get("policy.claim_support", 0.80))
            supported = all(v["label"] == "supports" and v["confidence"] >= threshold for v in verdicts)
            span.set(claims=len(claims), supported=supported, verdicts=[v["label"] for v in verdicts])
            if supported:
                return {}
            query = (state.get("query") or {}).get("rewritten") or state["message"]
            chunks = retrieve(query, rt.settings, conn=rt.kb_conn, embedder=rt.embedder).chunks
            retry = grounded_answer(query, chunks, rt.llm, history=self.window(state), original=state["message"])
            if not retry.grounded.abstained:
                again = rt.decider.check_claims([(c, "\n".join(ch.text for ch in chunks)) for c in
                                                 sentences(re.sub(r"\[[^\]]+\]", "", retry.text)) if len(c.split()) > 3])
                if again and all(v["label"] == "supports" and v["confidence"] >= threshold for v in again):
                    result.update(answer=retry.text, citations=[c.model_dump() for c in retry.grounded.citations])
                    return {"answer": retry.text, "result": result}
            result.update(kind="abstain", answer=ABSTAIN_TEXT, citations=[])
            result.setdefault("notes", []).append("answer check failed twice; abstained")
            return {"answer": ABSTAIN_TEXT, "result": result}

    def single_tool(self, state: dict) -> dict:
        rt = self.rt
        if rt.profile.get("sql.mode", "templates") == "text_to_sql" and state.get("route") in SQL_ROUTES \
                and (state.get("decision") or {}).get("answers", {}).get("wants_change", {}).get("noul", 0) < 0.5:
            return self.text_to_sql(state)
        with self.span(state, "single_tool") as span:
            reading = state.get("image_reading") or {}
            image_event = {**reading["event"], "_flagged": reading.get("flagged", [])} if reading.get("event") else None
            proposal = arguments.propose(state.get("route") or "", state.get("decision") or {}, state["message"],
                                         self.window(state), state.get("slots") or {}, rt.today, image_event)
            span.set(tool=proposal.tool, args=proposal.args, reason=proposal.reason)
            if proposal.clarify or not proposal.tool:
                text = proposal.clarify or prompts.CLARIFY_GENERIC
                return {"answer": text, "result": TurnResult(kind="clarify", answer=text,
                                                             route=state.get("route")).model_dump()}
            spec = rt.registry.get(proposal.tool)
            if spec and spec.write:
                return self._propose_write(state, proposal.tool, proposal.args)
            result, note = self.screen_untrusted(state, rt.run_tool(proposal.tool, proposal.args, state["account_id"]))
            calls = [result]
            if result.get("suggest") == "search_books" and rt.caps.tools:
                calls.append(rt.run_tool("search_books", {"query": proposal.args.get("title") or state["message"]},
                                         state["account_id"]))
            answer = " ".join(_format_tool_answer(r) for r in calls)
            slots = _slots_after(state.get("slots") or {}, calls)
            span.set(ok=result.get("ok"), source=result.get("source"), ms=result.get("ms"))
            notes = state.get("notes", []) + ([note] if note else [])
            return {"answer": answer, "tool_calls": calls, "slots": slots, "notes": notes,
                    "result": TurnResult(kind="tool", answer=answer, route=state.get("route"), tool_calls=calls,
                                         sources=result.get("sources") or []).model_dump()}

    def text_to_sql(self, state: dict) -> dict:
        """E07: the chat model writes SQL; only the sandboxed read connection runs it."""
        from ..tools.text_to_sql import generate_sql

        with self.span(state, "text_to_sql") as span:
            sql = generate_sql(self.rt.llm, state["message"])
            result = self.rt.run_tool("run_sql", {"sql": sql}, state["account_id"])
            span.set(sql=sql, ok=result.get("ok"), stopped_by=(result.get("data") or {}).get("stopped_by"))
            answer = result.get("summary", "")
            if result.get("ok"):
                rows = result["data"]["rows"][:8]
                answer += "\n" + "\n".join(", ".join(f"{k}={v}" for k, v in row.items()) for row in rows)
            return {"answer": answer, "tool_calls": [result],
                    "result": TurnResult(kind="tool", answer=answer, route=state.get("route"),
                                         tool_calls=[result]).model_dump()}

    def _propose_write(self, state: dict, tool: str, args: dict) -> dict:
        if not self.rt.caps.writes:
            text = "Write actions such as bookings are not switched on at this build step."
            return {"answer": text, "result": TurnResult(kind="abstain", answer=text, route=state.get("route")).model_dump()}
        return {"pending_write": {"tool": tool, "args": args, "account_id": state["account_id"]}}

    def agent_reason(self, state: dict) -> dict:
        rt = self.rt
        observations = state.get("tool_calls") or []
        history = self.window(state)
        candidates = arguments.agent_candidates(state["message"], state.get("decision") or {}, history,
                                                state.get("slots") or {}, rt.today)
        with self.span(state, "agent_reason", mode=rt.profile.get("agent.mode", "json"), step=len(observations) + 1) as span:
            step = agent_mod.next_step(rt, state, observations, candidates, history)
            span.record_llm(step.reply if hasattr(step.reply, "provider") else None)
            span.set(action=step.action, tool=step.tool, args=step.args, reason=step.reason)
            plan = {"action": step.action, "tool": step.tool, "args": step.args, "reason": step.reason}
            if step.action == "call_tool":
                spec = rt.registry.get(step.tool or "")
                if spec is None:
                    plan = {"action": "stop", "reason": f"unknown tool {step.tool!r} rejected by the registry"}
                elif any(agent_mod.call_key(o["tool"], o.get("args")) == agent_mod.call_key(step.tool, step.args)
                         for o in observations):
                    plan = {"action": "stop", "reason": f"repeat: {step.tool} with the same arguments"}
                elif spec.write:
                    update = self._propose_write(state, step.tool, step.args or {})
                    update["notes"] = state.get("notes", []) + ["agent proposed a write; sent to the risk gate"]
                    return {**update, "action": "agent", "answer": ""} if "pending_write" in update else {
                        **update, "action": "agent_done"}
            if plan["action"] != "call_tool":
                answer = step.answer if plan["action"] == "final" and step.answer else None
                if not answer:
                    answer = rt.llm.final_answer(state["message"], observations).text if observations else \
                        "No tool result was available for this request."
                notes = state.get("notes", []) + [f"agent stopped: {plan['reason']}"]
                result = TurnResult(kind="agent", answer=answer, route=state.get("route"), tool_calls=observations,
                                    notes=[plan["reason"]])
                return {"answer": answer, "notes": notes, "action": "agent_done", "result": result.model_dump(),
                        "slots": _slots_after(state.get("slots") or {}, observations)}
            return {"notes": state.get("notes", []), "action": "agent", "pending_call": plan}

    def agent_act(self, state: dict) -> dict:
        plan = state.get("pending_call") or {}
        with self.span(state, "agent_act", tool=plan.get("tool"), args=plan.get("args")) as span:
            result, note = self.screen_untrusted(state, self.rt.run_tool(plan["tool"], plan.get("args") or {},
                                                                         state["account_id"]))
            span.set(ok=result.get("ok"), source=result.get("source"))
            return {"tool_calls": (state.get("tool_calls") or []) + [result], "pending_call": None,
                    "notes": state.get("notes", []) + ([note] if note else [])}

    def risk_gate(self, state: dict) -> dict:
        rt = self.rt
        pending = state["pending_write"]
        with self.span(state, "risk_gate", tool=pending["tool"]) as span:
            gate_state = {"request": state["message"], "history": jev_history(_history(state)), "action": pending,
                          "session": {"account_id": state["account_id"]}}
            before = dict(rt.decider.usage_totals)
            decision = rt.decider.decide(gate_state, qcat.wire(qcat.gate_catalogue()))
            span.set(**_usage_delta(rt.decider, before))
            if not decision.ok:
                decision = StubDecider().decide(gate_state, qcat.wire(qcat.gate_catalogue()))
            explicit = decision.noul("explicit", 0.0) or 0.0
            own = decision.noul("own_account", 0.0) or 0.0
            impact = decision.score("impact", 0.0) or 0.0
            span.set(explicit=explicit, own_account=own, impact=impact)
            if pending.get("account_id") != state["account_id"] or own < 0.5:
                text = prompts.REFUSE_OTHER_ACCOUNT
                return {"pending_write": None, "answer": text,
                        "result": TurnResult(kind="refuse", answer=text, route=state.get("route")).model_dump()}
            if explicit < 0.5:
                text = "The write was not clearly requested, so nothing was changed. " + prompts.CLARIFY_GENERIC
                return {"pending_write": None, "answer": text,
                        "result": TurnResult(kind="clarify", answer=text, route=state.get("route")).model_dump()}
            pending = {**pending, "gate": {"explicit": explicit, "own_account": own, "impact": impact},
                       "prompt": _confirm_text(pending)}
            result = TurnResult(kind="confirm", answer=pending["prompt"], route=state.get("route"),
                                pending_write=pending, tool_calls=state.get("tool_calls") or [])
            return {"pending_write": pending, "answer": pending["prompt"], "result": result.model_dump()}

    def confirm(self, state: dict) -> dict:
        pending = state["pending_write"]
        decision = interrupt({"pending_write": pending, "prompt": pending["prompt"]})
        confirmed = bool(decision.get("confirm")) if isinstance(decision, dict) else bool(decision)
        with self.span(state, "confirm", confirmed=confirmed, tool=pending["tool"]) as span:
            if not confirmed:
                text = prompts.CANCELLED
                result = TurnResult(kind="tool", answer=text, route=state.get("route"),
                                    tool_calls=state.get("tool_calls") or [], notes=["write cancelled"])
                return {"pending_write": None, "answer": text, "result": result.model_dump()}
            outcome = self.rt.run_tool(pending["tool"], pending["args"], state["account_id"], allow_write=True)
            span.set(ok=outcome.get("ok"))
            text = _format_tool_answer(outcome)
            calls = (state.get("tool_calls") or []) + [outcome]
            result = TurnResult(kind="tool", answer=text, route=state.get("route"), tool_calls=calls,
                                notes=["write confirmed"])
            return {"pending_write": None, "answer": text, "tool_calls": calls, "result": result.model_dump()}

    def respond(self, state: dict) -> dict:
        with self.span(state, "respond") as span:
            result = dict(state.get("result") or TurnResult(kind="error", answer=state.get("answer") or "").model_dump())
            result.setdefault("route", state.get("route"))
            result["decision"] = state.get("decision")
            result["flags"] = sorted(set((result.get("flags") or []) + (state.get("flags") or [])))
            result["notes"] = (state.get("notes") or []) + (result.get("notes") or [])
            result["trace_id"] = state["trace_id"]
            if not result.get("query"):
                result["query"] = state.get("query") or {"original": state.get("message")}
            span.set(kind=result["kind"])
            update = {"result": result}
            if result["kind"] != "confirm":
                update["messages"] = [AIMessage(result["answer"])]
            return update


def _slots_after(slots: dict, calls: list[dict]) -> dict:
    slots = dict(slots)
    for call in calls:
        if not call.get("ok"):
            continue
        if call["tool"] == "find_free_rooms" and call["data"]["rooms"]:
            data = call["data"]
            slots["last_room_search"] = {"rooms": [r["room_id"] for r in data["rooms"]], "date": data["date"],
                                         "start": data["start"], "end": data["end"]}
        if call["tool"] == "check_book" and call.get("data"):
            slots["last_book"] = call["data"][0]["isbn"]
    return slots


def _confirm_text(pending: dict) -> str:
    args = pending["args"]
    if pending["tool"] == "book_room":
        return prompts.CONFIRM_BOOKING.format(room=args["room_id"], date=args["date"], start=args["start"], end=args["end"])
    if pending["tool"] == "place_hold":
        return prompts.CONFIRM_HOLD.format(isbn=args["isbn"], title=args.get("title", "catalogue record"))
    return prompts.CONFIRM_EVENT.format(title=args.get("title"), date=args.get("date"), start=args.get("start") or "?",
                                        end=args.get("end") or "?", location=args.get("location") or "?")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:12]


def citations_from(result: dict) -> list[Citation]:
    return [Citation(**c) for c in result.get("citations") or []]
