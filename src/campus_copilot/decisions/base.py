"""One `Decider` protocol with three implementations: Laya (local or HTTP), the stub, and the LLM router.

All three return the same `Decision`, so the graph never knows which one ran.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Protocol

from . import questions as qcat


@dataclass
class Decision:
    ok: bool
    answers: dict
    decider: str
    model: str = ""
    usage: dict = field(default_factory=dict)
    ms: float = 0.0
    stub: bool = False
    status: int | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    def get(self, qid: str) -> dict:
        return self.answers.get(qid) or {}

    def choice(self, qid: str) -> tuple[str | None, float, dict]:
        answer = self.get(qid)
        return answer.get("choice"), float(answer.get("confidence", 0.0) or 0.0), answer.get("probabilities", {})

    def noul(self, qid: str, default: float | None = None) -> float | None:
        value = self.get(qid).get("noul")
        return float(value) if value is not None else default

    def score(self, qid: str, default: float | None = None) -> float | None:
        value = self.get(qid).get("score")
        return float(value) if value is not None else default

    def as_dict(self) -> dict:
        return {"ok": self.ok, "decider": self.decider, "model": self.model, "usage": self.usage,
                "ms": round(self.ms, 1), "stub": self.stub, "status": self.status, "error": self.error,
                "answers": self.answers, "notes": self.notes}


class Decider(Protocol):
    name: str
    stub: bool

    def decide(self, state: dict, questions: dict) -> Decision: ...


class DeciderMixin:
    """Shared multi-request helpers built on `decide`."""

    name = "decider"
    stub = False
    workers = 8

    @property
    def usage_totals(self) -> dict:
        """Running request and token counts, so a trace span can record what its decisions cost."""
        if "_usage" not in self.__dict__:
            self.__dict__["_usage"] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        return self.__dict__["_usage"]

    def count(self, decision: Decision) -> Decision:
        totals = self.usage_totals
        totals["calls"] += 1
        totals["input_tokens"] += int(decision.usage.get("input_tokens", 0) or 0)
        totals["output_tokens"] += int(decision.usage.get("output_tokens", 0) or 0)
        return decision

    def decide(self, state: dict, questions: dict) -> Decision:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def decide_many(self, states: list, questions: dict) -> list[Decision]:
        """The same questions over several states: one request per state, run in parallel.

        Laya in local mode overrides this with one batched forward pass per checkpoint.
        """
        if not states:
            return []
        with ThreadPoolExecutor(max_workers=max(1, min(self.workers, len(states)))) as pool:
            return list(pool.map(lambda state: self.decide(state, questions), states))

    def judge_passages(self, query: str, passages: list[str]) -> list[dict]:
        """One question set per passage; returns relevant/has_answer/injection/contradicts Nouls."""
        spec = qcat.wire(qcat.passage_catalogue())
        verdicts = []
        for decision in self.decide_many([{"query": query, "passage": text} for text in passages], spec):
            if not decision.ok:
                verdicts.append({"relevant": 1.0, "has_answer": 0.5, "injection": 0.0, "contradicts": 0.0,
                                 "error": decision.error})
            else:
                verdicts.append({qid: decision.noul(qid, 0.0) for qid in spec})
        return verdicts

    def check_claims(self, pairs: list[tuple[str, str]]) -> list[dict]:
        spec = qcat.wire(qcat.claim_catalogue())
        out = []
        for decision in self.decide_many([{"claim": claim, "passage": passage} for claim, passage in pairs], spec):
            label, confidence, probs = decision.choice("claim_support")
            out.append({"label": label, "confidence": confidence, "probabilities": probs, "ok": decision.ok})
        return out


def get_decider(settings, kind: str | None = None, session=None, llm=None):
    """`router.kind`: `laya` (falls back to the stub when Laya is unavailable), `keyword` (the stub), or `llm`."""
    from .stub import StubDecider

    kind = kind or settings.profile.get("router.kind", "laya")
    if kind == "keyword":
        return StubDecider()
    if kind == "llm":
        from ..llm.client import get_llm
        from .llm_router import LLMRouter

        return LLMRouter(llm or get_llm(settings, role="chat"))
    if kind == "laya" and settings.has_laya:
        from .laya import LayaDecider

        return LayaDecider(settings, session=session)
    return StubDecider()
