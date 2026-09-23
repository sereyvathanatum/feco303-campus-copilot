"""Date and time helpers: relative days, weekday names, and clock times into ISO values."""

from __future__ import annotations

import datetime as dt
import re

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_TIME = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*$", re.IGNORECASE)


def resolve_date(value: str | dt.date | None, today: dt.date) -> dt.date:
    if isinstance(value, dt.date):
        return value
    text = (value or "today").strip().lower()
    if text == "today":
        return today
    if text == "tomorrow":
        return today + dt.timedelta(days=1)
    if text in WEEKDAYS:
        return today + dt.timedelta(days=(WEEKDAYS.index(text) - today.weekday()) % 7)
    return dt.date.fromisoformat(text)


def normalize_time(value: str | None, default_pm: bool = False) -> str | None:
    """'2 pm' -> '14:00'; '14:30' -> '14:30'; bare '2' -> '14:00' when default_pm (campus afternoon hours)."""
    if value is None:
        return None
    match = _TIME.match(str(value))
    if not match:
        raise ValueError(f"unreadable time {value!r}; use HH:MM")
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), (match.group(3) or "").lower()
    if meridiem == "pm" and hour < 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    elif not meridiem and default_pm and 1 <= hour <= 6:
        hour += 12
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"time out of range: {value!r}")
    return f"{hour:02d}:{minute:02d}"


def minutes_between(start: str, end: str) -> int:
    h1, m1 = map(int, start.split(":"))
    h2, m2 = map(int, end.split(":"))
    return (h2 * 60 + m2) - (h1 * 60 + m1)


def week_dates(day: dt.date) -> dict[str, dt.date]:
    monday = day - dt.timedelta(days=day.weekday())
    return {name: monday + dt.timedelta(days=i) for i, name in enumerate(WEEKDAYS)}
