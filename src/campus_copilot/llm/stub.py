"""Deterministic stub model for offline mode (docs/implementation-plan.md §8.2).

Replies are keyed on the task tag that each caller passes with a structured
payload, so the stub never has to parse a prompt. Every reply is marked `stub`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..schemas import ABSTAIN_TEXT
from ..textutil import coverage, has_khmer, sentences, terms
from .nim import LLMReply

ANSWER_COVERAGE = 0.6
FOLLOW_UP = re.compile(r"^\s*(and|also|what about|how about|and what about)\b[\s,]*(for|the|with|on|in)?\s*(?P<rest>.+?)\s*\??\s*$",
                       re.IGNORECASE)


class StubClient:
    provider = "stub"
    model = "stub-model"
    name = "stub"

    def __init__(self, reason: str = "offline mode") -> None:
        self.reason = reason

    def complete(self, messages: list[dict], *, task: str = "", payload: dict | None = None, **_: object) -> LLMReply:
        payload = payload or {}
        handler = getattr(self, f"_task_{task.replace('-', '_')}", None)
        text = handler(payload) if handler else "Stub reply."
        tokens_in = sum(len(str(m.get("content", "")).split()) for m in messages)
        return LLMReply(text=text, model=self.model, provider="stub", tokens_in=tokens_in,
                        tokens_out=len(text.split()), ms=0.0, stub=True, notes=[f"STUB ({self.reason})"])

    # ------------------------------------------------------------------ tasks
    def _task_grounded_answer(self, payload: dict) -> str:
        question = payload.get("question", "")
        best, best_score = None, 0.0
        for passage in payload.get("passages", []):
            score = coverage(question, passage["text"])
            if score > best_score:
                best, best_score = passage, score
        if best is None or best_score < ANSWER_COVERAGE:
            return json.dumps({"answer": ABSTAIN_TEXT, "citations": [], "abstained": True})
        ranked = sorted(sentences(best["text"]), key=lambda s: -coverage(question, s))
        answer = " ".join(ranked[:2]) if ranked else best["text"][:300]
        citation = {"source_id": best["source_id"], "page": best.get("page"), "section": best.get("section")}
        return json.dumps({"answer": answer, "citations": [citation], "abstained": False}, ensure_ascii=False)

    def _task_condense(self, payload: dict) -> str:
        message = payload.get("message", "").strip()
        match = FOLLOW_UP.match(message)
        if match and match.group("rest"):
            return f"What are the rules for {match.group('rest').rstrip('?. ')}?"
        return message

    def _task_probe(self, payload: dict) -> str:
        words = terms(payload.get("text", ""))[:4]
        return f"What does {payload.get('title', 'the document')} say about {' '.join(words) or 'its main rule'}?"

    def _task_small_reply(self, payload: dict) -> str:
        return ("Hello. The CamTech campus assistant answers handbook, timetable, deadline, room, library, weather, "
                "currency, and course-concept questions for the demo campus.")

    def _task_final_answer(self, payload: dict) -> str:
        parts = []
        for result in payload.get("tool_results", []):
            summary = result.get("summary") or json.dumps(result.get("data"), ensure_ascii=False)[:300]
            if result.get("attribution"):
                summary += f" (Source: {result['attribution']})"
            parts.append(summary)
        return " ".join(parts) or "No tool returned a result."

    def _task_agent_step(self, payload: dict) -> str:
        called = {(o["tool"], json.dumps(o.get("args", {}), sort_keys=True)) for o in payload.get("observations", [])}
        for candidate in payload.get("candidate_tools", []):
            key = (candidate["tool"], json.dumps(candidate.get("args", {}), sort_keys=True))
            if key not in called:
                return json.dumps({"action": "call_tool", "tool": candidate["tool"], "args": candidate.get("args", {})})
        answer = self._task_final_answer({"tool_results": payload.get("observations", [])})
        return json.dumps({"action": "final", "answer": answer}, ensure_ascii=False)

    def _task_read_image(self, payload: dict) -> str:
        """Canned reading: the generator's manifest records what a reader returns for each image."""
        path = Path(payload.get("image_path", ""))
        manifest = path.parent / "manifest.json"
        if manifest.is_file():
            entries = json.loads(manifest.read_text(encoding="utf-8"))
            entry = entries.get(path.name)
            if entry:
                reading = entry.get("stub_reading", entry)
                return json.dumps({"transcription": reading["transcription"], "event": reading["event"]},
                                  ensure_ascii=False)
        return json.dumps({"transcription": "", "event": {}})

    def _task_judge(self, payload: dict) -> str:
        score = coverage(payload.get("answer", ""), " ".join(payload.get("passages", [])))
        return json.dumps({"score": max(1, min(5, round(1 + 4 * score))), "reason": "term overlap (stub judge)"})

    def _task_router(self, payload: dict) -> str:
        from ..decisions.stub import StubDecider

        decision = StubDecider().decide(payload.get("state", {}), payload.get("questions", {}))
        return json.dumps(decision.answers, ensure_ascii=False)

    def _task_generic(self, payload: dict) -> str:
        return payload.get("text", "Stub reply.") if not has_khmer(payload.get("text", "")) else payload["text"]
