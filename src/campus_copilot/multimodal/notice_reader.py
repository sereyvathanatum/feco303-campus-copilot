"""Read a photographed notice into a draft calendar event (docs/implementation-plan.md §8.9).

1. The vision model returns one structured reply: a plain transcription and an
   `ExtractedEvent{title, date, start, end, location}`.
2. The decision model checks each field with an `<field>_supported` Noul over
   `{transcription, field_value}`. Unsupported fields are blanked and flagged.
3. The draft goes to the confirmation step; `add_event` writes only after Confirm.
"""

from __future__ import annotations

import datetime as dt
import re
from concurrent.futures import ThreadPoolExecutor

from pydantic import ValidationError

from .. import config
from ..decisions import questions as qcat
from ..schemas import ExtractedEvent
from ..tools.dates import normalize_time

MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                       "september", "october", "november", "december"], start=1)}
SUPPORTED = 0.5


def normalize_event(event: dict, today: dt.date) -> dict:
    """ISO date and HH:MM times; values that cannot be read become None."""
    out = {k: (event or {}).get(k) for k in ("title", "date", "start", "end", "location")}
    date = str(out.get("date") or "").strip()
    if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        match = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", date)
        month = MONTHS.get(match.group(2).lower()) if match else None
        out["date"] = dt.date(int(match.group(3)), month, int(match.group(1))).isoformat() if match and month else None
    for key in ("start", "end"):
        try:
            out[key] = normalize_time(str(out[key]).replace(".", ":")) if out.get(key) else None
        except ValueError:
            out[key] = None
    if out.get("location"):
        room = re.search(r"\b[A-D]-\d{3}\b", str(out["location"]))
        out["location"] = room.group(0) if room else str(out["location"]).strip()
    try:
        return ExtractedEvent.model_validate(out).model_dump()
    except ValidationError:
        return {k: None for k in out}


def check_fields(decider, transcription: str, event: dict) -> dict[str, float]:
    catalogue = qcat.event_catalogue()

    def one(name: str) -> tuple[str, float]:
        value = event.get(name)
        if not value:
            return name, 0.0
        qid = f"{name}_supported"
        decision = decider.decide({"transcription": transcription, "field_value": str(value)},
                                  qcat.wire(catalogue, [qid]))
        return name, float(decision.noul(qid, 0.0) or 0.0) if decision.ok else 0.5

    with ThreadPoolExecutor(max_workers=5) as pool:
        return dict(pool.map(one, qcat.EVENT_FIELDS))


def read_notice(rt, image_path: str) -> dict:
    today = config.today(rt.settings.profile)
    data, reply = rt.llm.read_image(image_path, today.isoformat())
    transcription = str(data.get("transcription") or "")
    event = normalize_event(data.get("event") or {}, today)
    before = dict(rt.decider.usage_totals)
    checks = check_fields(rt.decider, transcription, event)
    flagged = [name for name, score in checks.items() if event.get(name) and score < SUPPORTED]
    if event.get("start") and event.get("end") and event["end"] <= event["start"]:
        flagged += [n for n in ("start", "end") if n not in flagged]  # code check: a range must move forward
    missing = [name for name in ("title", "date") if not event.get(name)]
    for name in flagged:
        event[name] = None
    after = rt.decider.usage_totals
    return {"transcription": transcription, "event": event, "checks": checks, "flagged": flagged,
            "missing": missing + [n for n in flagged if n in ("title", "date") and n not in missing],
            "decider_tokens_in": after["input_tokens"] - before["input_tokens"], "_reply": reply,
            "stub": reply.stub}
