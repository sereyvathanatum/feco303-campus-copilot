"""One `Decider` protocol with three implementations: Jev (HTTP), the stub, and the LLM router.

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

    def decide(self, state: dict, questions: dict) -> Decision:  # pragma: no cover - implemented by subclasses
        raise NotImplementedError

    def judge_passages(self, query: str, passages: list[str]) -> list[dict]:
        """One request per passage, run in parallel; returns relevant/has_answer/injection/contradicts Nouls."""
        spec = qcat.wire(qcat.passage_catalogue())

        def one(text: str) -> dict:
            decision = self.decide({"query": query, "passage": text}, spec)
            if not decision.ok:
                return {"relevant": 1.0, "has_answer": 0.5, "injection": 0.0, "contradicts": 0.0,
                        "error": decision.error}
            return {qid: decision.noul(qid, 0.0) for qid in spec}

        with ThreadPoolExecutor(max_workers=max(1, min(self.workers, len(passages) or 1))) as pool:
            return list(pool.map(one, passages))

    def check_claims(self, pairs: list[tuple[str, str]]) -> list[dict]:
        spec = qcat.wire(qcat.claim_catalogue())

        def one(pair: tuple[str, str]) -> dict:
            decision = self.decide({"claim": pair[0], "passage": pair[1]}, spec)
            label, confidence, probs = decision.choice("claim_support")
            return {"label": label, "confidence": confidence, "probabilities": probs, "ok": decision.ok}

        with ThreadPoolExecutor(max_workers=max(1, min(self.workers, len(pairs) or 1))) as pool:
            return list(pool.map(one, pairs))


def get_decider(settings, kind: str | None = None, session=None, llm=None):
    """`router.kind`: `jev` (falls back to the stub without a key), `keyword` (the stub), or `llm`."""
    from .stub import StubDecider

    kind = kind or settings.profile.get("router.kind", "jev")
    if kind == "keyword":
        return StubDecider()
    if kind == "llm":
        from ..llm.client import get_llm
        from .llm_router import LLMRouter

        return LLMRouter(llm or get_llm(settings, role="chat"))
    if kind == "jev" and settings.has_jev:
        from .jev import JevDecider

        return JevDecider(settings, session=session)
    return StubDecider()
