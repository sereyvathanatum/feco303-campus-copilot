"""Follow-up rewriting before retrieval (docs/implementation-plan.md §8.4.4).

Gate (`rag.condense_query`):
* `laya_gated` (default): only when the route is `handbook`, history is not empty, and
  the `follow_up` Noul reaches `policy.follow_up`;
* `always`: every RAG turn with history;
* `off`: retrieval uses the raw message.

The rewrite feeds retrieval only. Every course code, ISBN, date, and number in the
message must survive it, or the raw message is used and the fallback is logged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KEEP = re.compile(r"\b[A-Z]{2,5}\d{3}\b|\b97[89]\d{10}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d+(?:[.:,]\d+)*\b")


@dataclass
class CondenseResult:
    original: str
    rewritten: str | None = None
    ran: bool = False
    reason: str = ""
    fallback: bool = False
    replies: list = field(default_factory=list)

    @property
    def query(self) -> str:
        return self.rewritten or self.original

    def as_dict(self) -> dict:
        return {"original": self.original, "rewritten": self.rewritten, "ran": self.ran, "reason": self.reason,
                "fallback": self.fallback}


def must_keep(message: str) -> list[str]:
    return KEEP.findall(message)


def gate(mode: str, history: list[dict], route: str | None, follow_up: float | None, threshold: float) -> tuple[bool, str]:
    if mode == "off":
        return False, "rag.condense_query = off"
    if not history:
        return False, "no history in this thread"
    if mode == "always":
        return True, "rag.condense_query = always"
    if route not in (None, "handbook"):
        return False, f"route {route} is not handbook"
    if follow_up is None:
        return False, "no follow_up decision available"
    if follow_up >= threshold:
        return True, f"follow_up {follow_up:.2f} >= {threshold:.2f}"
    return False, f"follow_up {follow_up:.2f} < {threshold:.2f}"


def condense(message: str, history: list[dict], llm, mode: str, route: str | None = None,
             follow_up: float | None = None, threshold: float = 0.5) -> CondenseResult:
    result = CondenseResult(original=message)
    run, reason = gate(mode, history, route, follow_up, threshold)
    result.reason = reason
    if not run:
        return result
    rewritten, reply = llm.condense(message, history)
    result.replies.append(reply)
    result.ran = True
    missing = [token for token in must_keep(message) if token not in rewritten]
    if missing or not rewritten.strip():
        result.fallback = True
        result.reason += f"; rewrite dropped {missing or 'everything'}, raw message used"
        return result
    result.rewritten = rewritten if rewritten.strip() != message.strip() else None
    return result
