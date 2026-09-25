"""Node-by-node debug view of one turn: what each graph node read, what it did inside, what it returned.

Switch it on with any of:

* `--debug-nodes` on `cli ask`, `cli chat`, and `cli step N --chat` (add `--full` for untruncated text)
* `/nodes` inside `cli chat`
* `COPILOT_DEBUG_NODES=1` in the environment (also works for `cli demo` and `cli ui`)

For every node the graph runs, the view prints one block:

    ━━ [3] guard_and_route ━━ graph/nodes.py · Nodes.guard_and_route ━━ 412 ms
    purpose : ONE Laya request answers the guard, route, and argument questions together
    reads   : message, account_id, messages (history), image_text
      · <sub-steps the node reports while it runs, for example the state sent to Laya>
    returns : the partial state update the node hands back to LangGraph

The RAG node reports each internal stage (query, lexical hits, dense hits, fusion, rerank, passage
filter, context, prompt, raw reply, parsed answer), so a wrong answer can be traced to the first
stage whose output looks wrong. The whole record is also written to `runs/debug/<trace_id>.json`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from typing import Any

from .. import config
from .trace import redact

# node -> (code location, what the node is for, state keys it reads)
NODES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "begin": ("graph/nodes.py · Nodes.begin",
              "start the turn: reset per-turn fields, measure the history window", ("message", "messages", "turn")),
    "status": ("graph/nodes.py · Nodes.status", "steps 1-4: report the knowledge-base build instead of answering",
               ()),
    "read_image": ("graph/nodes.py · Nodes.read_image → multimodal/notice_reader.py",
                   "the vision model transcribes the notice; Laya checks each extracted field", ("image_path",)),
    "guard_and_route": ("graph/nodes.py · Nodes.guard_and_route → decisions/laya.py",
                        "ONE Laya request answers the guard, route, and argument questions together",
                        ("message", "account_id", "messages", "image_text")),
    "apply_policy": ("graph/nodes.py · Nodes.apply_policy → decisions/policy.py · decide_action",
                     "turn Laya's answers and the profile thresholds into one action (rag, tool, agent, ...)",
                     ("decision", "slots", "image_reading")),
    "condense_query": ("graph/nodes.py · Nodes.condense_query → rag/condense.py",
                       "rewrite a follow-up into a standalone search query, only when the gate opens",
                       ("message", "messages", "route", "decision")),
    "rag_answer": ("graph/nodes.py · Nodes.rag_answer → rag/retrieve.py, rag/rerank.py, rag/answer.py",
                   "retrieve passages, filter them, and answer from them with citations",
                   ("message", "query", "decision", "messages")),
    "verify_answer": ("graph/nodes.py · Nodes.verify_answer",
                      "Laya checks each answer sentence against its cited passage; regenerate once, then abstain",
                      ("result", "query")),
    "single_tool": ("graph/nodes.py · Nodes.single_tool → graph/arguments.py, tools/registry.py",
                    "fill the tool arguments from Laya's answers, run one registered tool",
                    ("route", "decision", "message", "slots")),
    "agent_reason": ("graph/nodes.py · Nodes.agent_reason → graph/agent.py",
                     "the bounded loop picks the next tool call or stops", ("message", "tool_calls", "decision")),
    "agent_act": ("graph/nodes.py · Nodes.agent_act", "run the call the agent picked", ("pending_call",)),
    "risk_gate": ("graph/nodes.py · Nodes.risk_gate", "Laya judges whether a write is explicit, own-account, low-impact",
                  ("pending_write", "message")),
    "confirm": ("graph/nodes.py · Nodes.confirm", "stop at interrupt() until the account confirms or cancels",
                ("pending_write",)),
    "small_reply": ("graph/nodes.py · Nodes.small_reply", "the small model answers greetings and small talk",
                    ("message",)),
    "respond": ("graph/nodes.py · Nodes.respond", "package the turn result and append the reply to the thread",
                ("result", "answer", "decision", "notes")),
}
for _kind in ("clarify", "refuse", "handoff", "abstain"):
    NODES[_kind] = ("graph/nodes.py · Nodes.fixed_reply", f"send the fixed {_kind} text chosen by the policy",
                    ("answer", "route"))


def enabled_from_env() -> bool:
    return os.environ.get("COPILOT_DEBUG_NODES", "").strip().lower() in {"1", "true", "yes", "on"}


def _clip(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return text[:limit] + f" … [{len(text) - limit} more chars; --full shows everything]"


def _plain(value: Any) -> Any:
    """State values as JSON-friendly data (LangChain messages become role + content)."""
    if hasattr(value, "type") and hasattr(value, "content"):
        return {"role": value.type, "content": value.content}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def answers_table(answers: dict) -> list[str]:
    """Decision answers as one line each: choice with confidence and runner-up, noul, or score."""
    lines = []
    for qid, a in answers.items():
        if not isinstance(a, dict):
            continue
        if "choice" in a:
            probs = sorted((a.get("probabilities") or {}).items(), key=lambda kv: -kv[1])
            runner = f"  (next: {probs[1][0]} {probs[1][1]:.2f})" if len(probs) > 1 else ""
            lines.append(f"{qid:<18} choice {a['choice']:<14} confidence {float(a.get('confidence', 0)):.2f}{runner}")
        elif "noul" in a:
            value = float(a["noul"])
            lines.append(f"{qid:<18} noul   {value:.2f}  {'#' * int(round(value * 20)):<20}")
        elif "score" in a:
            lines.append(f"{qid:<18} score  {float(a['score']):.2f}  confidence {float(a.get('confidence', 0)):.2f}")
    return lines


class NodeDebugger:
    """Collects and prints the node-by-node record of one turn (or one resume)."""

    def __init__(self, full: bool = False, out=None, save: bool = True) -> None:
        self.full = full
        self.out = out or sys.stdout
        self.save = save
        self.limit = None if full else 700
        self.records: list[dict] = []
        self.current: str | None = None
        self.state: dict = {}
        self.tracer = None
        self.trace_id = ""

    # ------------------------------------------------------------------ output
    def _print(self, line: str = "") -> None:
        print(line, file=self.out, flush=True)

    def _value(self, value: Any, indent: str = "      ") -> str:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(_plain(value), ensure_ascii=False, indent=2, default=str)
        return "\n".join(indent + line for line in _clip(text, self.limit).splitlines())

    # ------------------------------------------------------------------- turns
    def start(self, message: str, trace_id: str, thread: str, tracer=None, resume: bool = False) -> None:
        self.records, self.current, self.state = [], None, {}
        self.tracer, self.trace_id = tracer, trace_id
        what = "resume" if resume else "turn"
        self._print()
        self._print(f"══ node debug: {what} {trace_id} · thread {thread} " + "═" * 30)
        if message:
            self._print(f"   message: {message!r}")

    def snapshot(self, values: dict) -> None:
        """The full state after the last node; the next node reads from it."""
        self.state = dict(values)

    def _open(self, node: str) -> dict:
        if self.current == node and self.records and self.records[-1]["node"] == node \
                and "returns" not in self.records[-1]:
            return self.records[-1]
        self.current = node
        code, purpose, reads = NODES.get(node, ("graph/nodes.py", "", ()))
        record = {"node": node, "index": len(self.records) + 1, "code": code, "purpose": purpose,
                  "reads": {k: _plain(self.state.get(k)) for k in reads if k in self.state}, "steps": []}
        self.records.append(record)
        self._print()
        self._print(f"━━ [{record['index']}] {node} ━━ {code}")
        if purpose:
            self._print(f"   purpose : {purpose}")
        if record["reads"]:
            self._print("   reads   :")
            for key, value in record["reads"].items():
                if key == "messages":
                    value = [f"{m['role']}: {m['content']}" for m in value][-6:] if isinstance(value, list) else value
                self._print(f"    {key} =")
                self._print(self._value(value))
        return record

    def step(self, node: str, title: str, data: Any = None) -> None:
        """A sub-step reported from inside a running node."""
        record = self._open(node)
        record["steps"].append({"title": title, "data": _plain(data)})
        self._print(f"   · {title}")
        if data not in (None, "", [], {}):
            self._print(self._value(data))

    def node_done(self, node: str, update: Any) -> None:
        record = self._open(node)
        record["returns"] = _plain(update) if update is not None else {}
        ms = self._span_ms(node)
        if ms is not None:
            record["ms"] = ms
        self._print("   returns :" + ("  (no change to the state)" if not update else ""))
        if update:
            for key, value in update.items():
                if key == "decision" and isinstance(value, dict):
                    value = {k: value.get(k) for k in ("decider", "model", "ms", "stub", "notes")}
                    value["answers"] = "(see the Laya answers above)"
                if key == "result" and isinstance(value, dict):
                    value = {k: value[k] for k in ("kind", "answer", "route", "citations", "tool_calls")
                             if value.get(k) not in (None, [], "")}
                if key == "sources" and isinstance(value, list):
                    value = [f"#{s.get('rank')} {s.get('citation')} "
                             f"{'used' if s.get('in_context') else 'DROPPED'}" for s in value]
                self._print(f"    {key} =")
                self._print(self._value(value))
        if ms is not None:
            self._print(f"   time    : {ms:.1f} ms")
        self.current = None

    def interrupted(self, payload: Any) -> None:
        self._print()
        self._print("━━ interrupt ━━ the graph paused in `confirm`; `cli ask --yes/--no` or the chat prompt resumes it")
        self._print(self._value(payload))
        self.records.append({"node": "__interrupt__", "payload": _plain(payload)})

    def finish(self) -> str | None:
        path = None
        if self.save and self.records:
            folder = config.runs_dir() / "debug"
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"{self.trace_id or dt.datetime.now().strftime('%H%M%S')}.json"
            existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
            path.write_text(json.dumps(existing + redact(self.records), ensure_ascii=False, indent=1, default=str),
                            encoding="utf-8")
        self._print()
        order = " → ".join(r["node"] for r in self.records if r["node"] != "__interrupt__")
        self._print(f"══ path through the graph: {order}")
        if path:
            self._print(f"══ full record: {path}")
        return str(path) if path else None

    def _span_ms(self, node: str) -> float | None:
        if self.tracer is None:
            return None
        for span in reversed(self.tracer.spans):
            if span.span == node:
                return round(span.ms, 1)
        return None


class NullDebugger:
    """Used when node debugging is off: every call is a no-op, so nodes can report unconditionally."""

    full = False

    def step(self, node: str, title: str, data: Any = None) -> None:
        return None

    def __bool__(self) -> bool:
        return False
