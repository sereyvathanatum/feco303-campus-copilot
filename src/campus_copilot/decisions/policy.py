"""Pure, unit-tested functions that turn a `Decision` into an action (docs/implementation-plan.md §8.3).

Starting thresholds come from the profile's `[policy]` table and are tuned in
E04, E05, and E13; they are not fixed defaults.

    guards:   any of injection/other_account/misconduct >= block  -> refuse
              >= review                                            -> continue, flag the turn for review
              guard_severity >= severity_refuse while a flag is up  -> refuse
    staff:    wants_staff >= wants_staff                            -> handoff
    route:    confidence < low                                      -> clarify
              low <= confidence < high and wants_change             -> clarify before any write
    details:  a required argument = not_stated, or a "stated?" Noul < stated -> targeted clarify
              missing_info >= missing_info with all arguments stated -> generic clarify
    shape:    several_sources >= several_sources                    -> agent loop, else single handler
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..llm import prompts
from .base import Decision
from .questions import DATA_ROUTES

GUARDS = ("injection", "other_account", "misconduct")
RAG_ROUTES = ("handbook", "out_of_scope")  # both end in retrieval, which answers or abstains
REFUSALS = {"injection": prompts.REFUSE_INJECTION, "other_account": prompts.REFUSE_OTHER_ACCOUNT,
            "misconduct": prompts.REFUSE_MISCONDUCT}


@dataclass
class Thresholds:
    block: float = 0.70
    review: float = 0.35
    severity_refuse: float = 2.0
    wants_staff: float = 0.60
    confidence_low: float = 0.50
    confidence_high: float = 0.80
    stated: float = 0.50
    missing_info: float = 0.80
    several_sources: float = 0.60
    follow_up: float = 0.50

    @classmethod
    def from_profile(cls, profile) -> "Thresholds":
        pol = profile.get("policy", {}) or {}
        guards = profile.get("guards", {}) or {}
        return cls(
            block=float(guards.get("block", pol.get("block", 0.70))),
            review=float(guards.get("review", pol.get("review", 0.35))),
            severity_refuse=float(pol.get("severity_refuse", 2.0)),
            wants_staff=float(pol.get("wants_staff", 0.60)),
            confidence_low=float(profile.get("router.confidence_low", 0.50)),
            confidence_high=float(profile.get("router.confidence_high", 0.80)),
            stated=float(pol.get("stated", 0.50)),
            missing_info=float(pol.get("missing_info", 0.80)),
            several_sources=float(pol.get("several_sources", 0.60)),
            follow_up=float(pol.get("follow_up", 0.50)),
        )


@dataclass
class Action:
    kind: str                     # refuse | handoff | clarify | small | rag | tool | agent | abstain
    route: str | None = None
    reason: str = ""
    reply: str | None = None      # fixed text for refuse, handoff, clarify
    flags: list[str] = field(default_factory=list)
    wants_change: bool = False
    confidence: float = 0.0


def guard(decision: Decision, t: Thresholds, enabled: bool = True) -> Action | None:
    if not enabled:
        return None
    flags, top_name, top_value = [], None, 0.0
    for name in GUARDS:
        value = decision.noul(name, 0.0) or 0.0
        if value >= t.review:
            flags.append(f"review:{name}")
        if value > top_value:
            top_name, top_value = name, value
    if top_name and top_value >= t.block:
        return Action("refuse", reason=f"{top_name} {top_value:.2f} >= block {t.block:.2f}",
                      reply=REFUSALS[top_name], flags=flags)
    severity = decision.score("guard_severity", 0.0) or 0.0
    if flags and severity >= t.severity_refuse:
        return Action("refuse", reason=f"guard_severity {severity:.2f} >= {t.severity_refuse:.2f} with {flags}",
                      reply=REFUSALS[top_name or "injection"], flags=flags)
    return Action("continue", flags=flags) if flags else None


def staff(decision: Decision, t: Thresholds, offices: dict) -> Action | None:
    value = decision.noul("wants_staff", 0.0) or 0.0
    if value < t.wants_staff:
        return None
    office = offices.get("fees", {})
    reply = prompts.HANDOFF.format(contact=office.get("contact", "the Fees Office"), hours=office.get("hours", ""))
    return Action("handoff", reason=f"wants_staff {value:.2f} >= {t.wants_staff:.2f}", reply=reply)


def missing_details(decision: Decision, route: str, t: Thresholds, has_slots: bool = False) -> Action | None:
    """Per-argument checks: a `not_stated` option or a low "stated?" Noul triggers a targeted clarify."""
    if route == "currency":
        direction, _, _ = decision.choice("currency_direction")
        if direction in (None, "not_stated"):
            return Action("clarify", route, "currency_direction = not_stated", prompts.CLARIFY_CONVERSION)
        if (decision.noul("amount_stated", 1.0) or 0.0) < t.stated:
            return Action("clarify", route, "amount_stated below threshold", prompts.CLARIFY_AMOUNT)
    if route == "rooms" and not has_slots:
        day, _, _ = decision.choice("day")
        if day in (None, "not_stated"):
            return Action("clarify", route, "day = not_stated", prompts.CLARIFY_DAY)
        time_of_day, _, _ = decision.choice("time_of_day")
        if time_of_day in (None, "not_stated"):
            return Action("clarify", route, "time_of_day = not_stated", prompts.CLARIFY_TIME)
    return None


def decide_action(decision: Decision, t: Thresholds, *, guards_enabled: bool = True, tools: bool = True,
                  agent: bool = True, offices: dict | None = None, has_slots: bool = False,
                  force_agent: str = "") -> Action:
    """The full policy for one turn. `has_slots`: memory holds the details a write needs (for example 'Book it.')."""
    flags: list[str] = []
    blocked = guard(decision, t, guards_enabled)
    if blocked and blocked.kind == "refuse":
        return blocked
    if blocked:
        flags = blocked.flags
    handoff = staff(decision, t, offices or {})
    if handoff:
        handoff.flags = flags
        return handoff
    route, confidence, probabilities = decision.choice("route")
    if route in RAG_ROUTES:
        # routes that lead to the same action pool their probability: a handbook/out_of_scope split still means RAG
        confidence = max(confidence, sum(float(probabilities.get(r, 0.0)) for r in RAG_ROUTES))
    several_hint = decision.noul("several_sources", 0.0) or 0.0
    if route in DATA_ROUTES and several_hint >= t.several_sources and agent and tools:
        # a multi-source request splits its route across the sources it needs; together they point to the agent
        confidence = max(confidence, sum(float(probabilities.get(r, 0.0)) for r in DATA_ROUTES))
    wants_change = (decision.noul("wants_change", 0.0) or 0.0) >= 0.5
    if route is None or confidence < t.confidence_low:
        return Action("clarify", route, f"route confidence {confidence:.2f} < {t.confidence_low:.2f}",
                      prompts.CLARIFY_ROUTE, flags, wants_change, confidence)
    if wants_change and confidence < t.confidence_high and not has_slots:
        return Action("clarify", route, f"write intent at route confidence {confidence:.2f} < {t.confidence_high:.2f}",
                      prompts.CLARIFY_GENERIC, flags, wants_change, confidence)
    if route == "chit_chat":
        return Action("small", route, "chit_chat", flags=flags, confidence=confidence)
    if route in ("handbook", "out_of_scope"):
        return Action("rag", route, f"route {route}", flags=flags, confidence=confidence)
    detail = missing_details(decision, route, t, has_slots)
    if detail:
        detail.flags, detail.confidence = flags, confidence
        return detail
    several = decision.noul("several_sources", 0.0) or 0.0
    if route in DATA_ROUTES and not tools:
        return Action("abstain", route, f"route {route} needs a lookup tool, which this build step has not added",
                      flags=flags, wants_change=wants_change, confidence=confidence)
    if (force_agent == "on" or (several >= t.several_sources and force_agent != "off")) and agent:
        return Action("agent", route, f"several_sources {several:.2f} >= {t.several_sources:.2f}"
                      if force_agent != "on" else "agent forced on", flags=flags, wants_change=wants_change,
                      confidence=confidence)
    if (decision.noul("missing_info", 0.0) or 0.0) >= t.missing_info and not has_slots:
        return Action("clarify", route, "missing_info above threshold with every argument stated",
                      prompts.CLARIFY_GENERIC, flags, wants_change, confidence)
    return Action("tool", route, f"route {route} (confidence {confidence:.2f})", flags=flags,
                  wants_change=wants_change, confidence=confidence)
