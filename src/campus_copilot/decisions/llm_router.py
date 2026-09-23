"""The "System 2" baseline: the chat model answers the same questions as structured JSON (E05).

Malformed or incomplete replies are counted, so E05 can compare latency, cost,
malformed outputs, and accuracy against Jev and the keyword stub.
"""

from __future__ import annotations

import time

from .base import Decision, DeciderMixin
from .stub import StubDecider


class LLMRouter(DeciderMixin):
    name = "llm"
    stub = False
    workers = 2

    def __init__(self, llm) -> None:
        self.llm = llm
        self.malformed = 0
        self.calls = 0

    def decide(self, state, questions: dict) -> Decision:
        started = time.perf_counter()
        data, reply = self.llm.route_json(state if isinstance(state, dict) else {"message": state}, questions)
        self.calls += 1
        ms = (time.perf_counter() - started) * 1000
        usage = {"input_tokens": reply.tokens_in, "output_tokens": reply.tokens_out}
        if not isinstance(data, dict):
            self.malformed += 1
            return Decision(False, {}, self.name, reply.model, usage, ms, stub=reply.stub,
                            error="malformed: reply was not a JSON object")
        answers, notes = {}, []
        filler = StubDecider()
        for qid, spec in questions.items():
            answer = data.get(qid)
            if not isinstance(answer, dict) or not self._valid(answer, spec):
                notes.append(f"malformed answer for {qid}; neutral default used")
                answer = filler._default(spec)
            answers[qid] = {**answer, "type": spec["type"]}
        if notes:
            self.malformed += 1
        return Decision(True, answers, self.name, f"{reply.provider}:{reply.model}", usage, ms, stub=reply.stub,
                        notes=notes + reply.notes)

    @staticmethod
    def _valid(answer: dict, spec: dict) -> bool:
        kind = spec["type"]
        try:
            if kind == "noul":
                return 0.0 <= float(answer["noul"]) <= 1.0
            if kind == "choice":
                return answer.get("choice") in spec["criteria"]
            return float(answer["score"]) >= 0.0
        except (KeyError, TypeError, ValueError):
            return False
