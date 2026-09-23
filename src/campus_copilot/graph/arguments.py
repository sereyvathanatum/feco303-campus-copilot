"""Argument filling for single tool calls: "select instead of generate".

Code finds candidates with regexes (amounts, times, ISBNs, quoted terms); the
decider answers only closed-set questions (course, day, conversion direction,
room features). Identity is never an argument: tools read the session account.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from ..tools.dates import normalize_time

ISBN = re.compile(r"\b97[89]\d{10}\b")
AMOUNT = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w:])")
KHMER_DIGITS = str.maketrans("០១២៣៤៥៦៧៨៩", "0123456789")
RANGE = re.compile(r"(?<![\d\-/])\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|–|to|until)\s*(\d{1,2})(?::(\d{2}))?"
                   r"\s*(am|pm)?\b(?![\-/]\d)", re.IGNORECASE)
AT_TIME = re.compile(r"\b(?:at|around|from)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.IGNORECASE)
CAPACITY = re.compile(r"\b(?:for|seats?|capacity)\s+(\d{1,3})\b|\b(\d{1,3})\s+(?:people|seats|persons)\b", re.IGNORECASE)
QUOTED = re.compile(r"['\"‘’“”]([^'\"‘’“”]{2,60})['\"‘’“”]")
CONCEPT = re.compile(r"\b(?:what (?:does|is|are)|explain|define|meaning of)\s+(?:an?\s+|the\s+)?(.+?)(?:\s+mean\b|\s+in\s+\w+|\?|$)", re.IGNORECASE)
DAY_WINDOWS = {"morning": ("09:00", "11:00"), "afternoon": ("14:00", "16:00"), "evening": ("17:00", "19:00")}


@dataclass
class Proposal:
    tool: str | None
    args: dict
    reason: str = ""
    clarify: str | None = None


def _clock(hour: str, minute: str | None, meridiem: str | None, fallback: str | None = None) -> str:
    meridiem = meridiem or fallback
    return normalize_time(f"{hour}:{minute or '00'}{' ' + meridiem if meridiem else ''}", default_pm=True)


def time_window(text: str) -> tuple[str, str] | None:
    match = RANGE.search(text)
    if match:
        h1, m1, a1, h2, m2, a2 = match.groups()
        return _clock(h1, m1, a1, a2), _clock(h2, m2, a2)
    match = AT_TIME.search(text)
    if match:
        start = _clock(*match.groups())
        hour = int(start[:2]) + 1
        return start, f"{hour:02d}:{start[3:]}"
    return None


def amount(text: str) -> float | None:
    text = text.translate(KHMER_DIGITS)
    for match in AMOUNT.finditer(text):
        whole = match.group(1).replace(",", "")
        if ISBN.fullmatch(whole):
            continue
        return float(whole + ("." + match.group(2) if match.group(2) else ""))
    return None


def concept_topic(text: str) -> str | None:
    quoted = QUOTED.search(text)
    if quoted:
        return quoted.group(1).strip()
    match = CONCEPT.search(text)
    return match.group(1).strip(" .?") if match else None


def _choice(decision: dict, qid: str) -> str | None:
    value = ((decision.get("answers") or {}).get(qid) or {}).get("choice")
    return None if value in (None, "not_stated") else value


def _noul(decision: dict, qid: str) -> float:
    return float(((decision.get("answers") or {}).get(qid) or {}).get("noul") or 0.0)


def history_text(history: list[dict]) -> list[str]:
    return [h.get("content") or h.get("text", "") for h in history if h.get("role") == "user"]


def propose(route: str, decision: dict, message: str, history: list[dict], slots: dict, today: dt.date,
            image_event: dict | None = None) -> Proposal:
    """Pick one tool and fill its arguments from the decision, the message, recent turns, and memory slots."""
    wants_change = _noul(decision, "wants_change") >= 0.5
    earlier = history_text(history)
    course, day = _choice(decision, "course"), _choice(decision, "day")
    if route == "timetable":
        args = {"course": course}
        if day and "this week" not in message.lower():
            args["day"] = day
        return Proposal("get_timetable", {k: v for k, v in args.items() if v}, "timetable lookup")
    if route == "deadlines":
        within = 7 if re.search(r"\bthis week\b", message, re.IGNORECASE) else None
        return Proposal("get_deadlines", {k: v for k, v in {"course": course, "within_days": within}.items()
                                          if v is not None}, "deadline lookup")
    if route == "calendar":
        if wants_change:
            event = dict(image_event or {})
            flagged = event.pop("_flagged", []) or []
            if flagged:
                fields = ", ".join(flagged)
                return Proposal(None, {}, f"unverified fields: {fields}",
                                f"The notice was read, but these fields could not be verified against its text: "
                                f"{fields}. Which values are correct?")
            if not event.get("title") or not event.get("date"):
                return Proposal(None, {}, "no event details", "Which event: a title and a date are needed.")
            return Proposal("add_event", {k: v for k, v in event.items() if v}, "event from the notice")
        start = today if not day else _resolve(day, today)
        return Proposal("get_calendar", {"from": start.isoformat(), "to": (start + dt.timedelta(days=30)).isoformat()},
                        "calendar lookup")
    if route == "rooms":
        last = slots.get("last_room_search")
        if wants_change and last and last.get("rooms"):
            return Proposal("book_room", {"room_id": last["rooms"][0], "date": last["date"], "start": last["start"],
                                          "end": last["end"], "purpose": "study"}, "memory: first room of the last search")
        window = time_window(message) or next((w for w in map(time_window, reversed(earlier)) if w), None)
        if not window:
            tod = _choice(decision, "time_of_day")
            window = DAY_WINDOWS.get(tod or "")
        if not window:
            return Proposal(None, {}, "no time window", "Which time window: a start and end time, for example 14:00-16:00?")
        args = {"date": day or "today", "start": window[0], "end": window[1]}
        if _noul(decision, "needs_projector") >= 0.5:
            args["needs_projector"] = True
        if _noul(decision, "needs_pcs") >= 0.5:
            args["needs_pcs"] = True
        seats = CAPACITY.search(message)
        if seats:
            args["min_capacity"] = int(seats.group(1) or seats.group(2))
        # a booking request with no earlier search runs the search first; the write needs a chosen room
        return Proposal("find_free_rooms", args, "free-room search" + (" before a booking" if wants_change else ""))
    if route == "library":
        isbn = ISBN.search(message) or next((m for m in (ISBN.search(t) for t in reversed(earlier)) if m), None)
        if wants_change:
            target = isbn.group(0) if isbn else slots.get("last_book")
            if not target:
                return Proposal(None, {}, "no book chosen", "Which book: an ISBN is needed to place a hold.")
            return Proposal("place_hold", {"isbn": target}, "hold request")
        if isbn and ISBN.search(message):
            return Proposal("check_book", {"isbn": isbn.group(0)}, "ISBN lookup")
        if re.search(r"\bloans?\b", message, re.IGNORECASE):
            return Proposal("get_loans", {}, "own loans")
        quoted = QUOTED.search(message)
        title = quoted.group(1) if quoted else re.sub(r"(?i)\b(is|are|the|book|books|available|in|library|on|shelf|"
                                                      r"there|a|an|any|about|do|does|have|has)\b|[?.!]", " ", message)
        title = re.sub(r"\s+", " ", title).strip()
        return Proposal("check_book", {"title": title or message}, "title lookup")
    if route == "weather":
        window = time_window(message)
        args = {"date": day or "today"}
        if window:
            args.update({"hour": window[0], "until": window[1]})
        return Proposal("campus_weather", args, "forecast")
    if route == "currency":
        direction = _choice(decision, "currency_direction")
        value = amount(message)
        if value is None:
            value = next((a for a in map(amount, reversed(earlier)) if a is not None), None)
        if not direction:
            return Proposal(None, {}, "direction not stated", "Which conversion: USD to KHR or KHR to USD?")
        if value is None:
            return Proposal(None, {}, "amount not found", "Which amount should be converted?")
        return Proposal("convert_currency", {"amount": value, "direction": direction}, "conversion")
    if route == "concept":
        topic = concept_topic(message) or message
        return Proposal("concept_summary", {"topic": topic}, "concept summary")
    return Proposal(None, {}, f"no tool for route {route}")


def _resolve(day: str, today: dt.date) -> dt.date:
    from ..tools.dates import resolve_date

    return resolve_date(day, today)


def agent_candidates(message: str, decision: dict, history: list[dict], slots: dict, today: dt.date) -> list[dict]:
    """Tool calls a deterministic planner would make for a multi-source request (the stub model's plan).

    Built from the keyword router's hits on the message; a live model chooses its own calls.
    """
    from ..decisions.stub import Context

    hits = Context({"message": message}).route_hits(message)
    order = ["rooms", "timetable", "deadlines", "calendar", "library", "weather", "currency", "concept"]
    calls: list[dict] = []
    window = time_window(message)
    answers = dict((decision or {}).get("answers") or {})
    answers["wants_change"] = {"type": "noul", "noul": 0.0}  # the plan holds read lookups; writes go through the gate
    reads_only = {**(decision or {}), "answers": answers}
    for route in [r for r in order if r in hits]:
        proposal = propose(route, reads_only, message, history, {}, today)
        if proposal.tool and not proposal.tool.startswith(("book_", "place_", "add_")):
            if route == "weather" and window:
                proposal.args.update({"hour": window[0], "until": window[1]})
            calls.append({"tool": proposal.tool, "args": proposal.args})
    return calls
