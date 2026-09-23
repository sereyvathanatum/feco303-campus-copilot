"""Grounded answers: retrieved chunks → `GroundedAnswer` with PDF-page or Markdown-section citations.

When no chunk survives retrieval and filtering, the answer is the fixed abstention
sentence and no model call is made.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..schemas import ABSTAIN_TEXT, GroundedAnswer
from .retrieve import ScoredChunk


@dataclass
class AnswerResult:
    grounded: GroundedAnswer
    text: str
    replies: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def passages_for(chunks: list[ScoredChunk]) -> list[dict]:
    return [{"source_id": c.source_id, "page": c.page, "section": c.section if not c.page else None, "text": c.text}
            for c in chunks]


def answer(question: str, chunks: list[ScoredChunk], llm, history: list[dict] | None = None,
           original: str | None = None) -> AnswerResult:
    if not chunks:
        grounded = GroundedAnswer(answer=ABSTAIN_TEXT, abstained=True)
        return AnswerResult(grounded, ABSTAIN_TEXT, notes=["no passages survived retrieval; abstained without a model call"])
    grounded, reply = llm.grounded_answer(question, passages_for(chunks), history=history, original=original)
    notes = list(reply.notes)
    if not grounded.abstained and not grounded.citations:
        notes.append("answer carries no valid citation")
    return AnswerResult(grounded, grounded.render(), [reply], notes)
