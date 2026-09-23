"""Campus tools over SQLite and the knowledge base (docs/implementation-plan.md §8.6).

Read tools use the authorizer-guarded read connection and take `account_id` from the
session context. Write tools (`book_room`, `place_hold`, `add_event`) use the write
connection and run only after the confirmation step.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, field_validator

from ..db import connection, queries
from ..schemas import ExtractedEvent
from .dates import minutes_between, normalize_time, resolve_date, week_dates
from .registry import ToolContext, ToolSpec

MAX_BOOKING_MINUTES = 120
MAX_DAYS_AHEAD = 7
MAX_ACTIVE_BOOKINGS = 3
MAX_ACTIVE_HOLDS = 3


def _read(ctx: ToolContext):
    return connection.read_connection(ctx.db_path)


def _write(ctx: ToolContext):
    return connection.write_connection(ctx.db_path)


# ---------------------------------------------------------------- arguments

class SearchArgs(BaseModel):
    query: str = Field(description="Search query for the approved handbook and course documents.")


class TimetableArgs(BaseModel):
    course: str | None = Field(None, description="Course code such as FECO303; omit for every enrolled course.")
    day: str | None = Field(None, description="today, tomorrow, a weekday name, or YYYY-MM-DD; omit for the week.")


class DeadlineArgs(BaseModel):
    course: str | None = Field(None, description="Course code; omit for every enrolled course.")
    within_days: int | None = Field(None, ge=0, le=120, description="Only deadlines within this many days.")


class FreeRoomArgs(BaseModel):
    date: str = Field(description="today, tomorrow, a weekday name, or YYYY-MM-DD.")
    start: str = Field(description="Start time, HH:MM (24-hour) or '2 pm'.")
    end: str = Field(description="End time, HH:MM (24-hour) or '4 pm'.")
    min_capacity: int | None = Field(None, ge=1, le=500, description="Minimum number of seats.")
    needs_projector: bool | None = Field(None, description="Only rooms with a projector.")
    needs_pcs: bool | None = Field(None, description="Only rooms with computers.")

    @field_validator("start", "end")
    @classmethod
    def _time(cls, value: str) -> str:
        return normalize_time(value, default_pm=True)


class BookArgs(BaseModel):
    isbn: str | None = Field(None, description="ISBN-13 of the book.")
    title: str | None = Field(None, description="Part of the book title.")


class NoArgs(BaseModel):
    pass


class CalendarArgs(BaseModel):
    date_from: str = Field(alias="from", description="First day: today, tomorrow, a weekday, or YYYY-MM-DD.")
    date_to: str = Field(alias="to", description="Last day: today, tomorrow, a weekday, or YYYY-MM-DD.")
    kind: str | None = Field(None, description="holiday, exam, seminar, deadline, or event.")

    model_config = {"populate_by_name": True}


class BookRoomArgs(BaseModel):
    room_id: str = Field(description="Room ID such as B-204.")
    date: str = Field(description="today, tomorrow, a weekday name, or YYYY-MM-DD.")
    start: str = Field(description="Start time, HH:MM.")
    end: str = Field(description="End time, HH:MM.")
    purpose: str = Field("study", description="Short purpose of the booking.")

    @field_validator("start", "end")
    @classmethod
    def _time(cls, value: str) -> str:
        return normalize_time(value, default_pm=True)


class HoldArgs(BaseModel):
    isbn: str = Field(description="ISBN-13 of the book to hold.")


# -------------------------------------------------------------------- reads

def search_handbook(ctx: ToolContext, args: SearchArgs) -> dict:
    from ..ingest import store as kb
    from ..rag.retrieve import retrieve

    conn = ctx.kb_conn or kb.connect()
    result = retrieve(args.query, ctx.settings, conn=conn, embedder=ctx.embedder, decider=ctx.decider)
    chunks = [c.as_dict() for c in result.chunks]
    summary = " ".join(f"{c['citation']} {c['text'][:200]}" for c in chunks[:3]) or "No passage matched."
    return {"data": {"chunks": chunks, "mode": result.mode}, "summary": summary, "sources": chunks}


def get_timetable(ctx: ToolContext, args: TimetableArgs) -> dict:
    conn = _read(ctx)
    course = args.course.upper() if args.course else None
    weekday = None
    if args.day:
        weekday = queries.weekday_of(resolve_date(args.day, ctx.today))
    rows = queries.timetable(conn, ctx.account_id, course, weekday)
    dates = week_dates(ctx.today)
    for row in rows:
        row["date_this_week"] = dates[row["weekday"]].isoformat()
    if not rows:
        enrolled = queries.enrolled_courses(conn, ctx.account_id)
        why = (f"{course} is not among the enrolled courses ({', '.join(enrolled)})" if course and course not in enrolled
               else "no sessions match")
        return {"data": [], "summary": f"No timetable entries: {why}."}
    parts = [f"{r['course_code']} {r['kind']}: {r['weekday'].capitalize()} {r['date_this_week']}, {r['start']}–{r['end']} "
             f"in room {r['room_id']}" for r in rows]
    return {"data": rows, "summary": "; ".join(parts) + "."}


def get_deadlines(ctx: ToolContext, args: DeadlineArgs) -> dict:
    rows = queries.deadlines(_read(ctx), ctx.account_id, ctx.now, args.course.upper() if args.course else None,
                             args.within_days)
    if not rows:
        return {"data": [], "summary": "No upcoming deadlines match."}
    parts = [f"{r['course_code']} '{r['title']}' due {r['due_at']} (weight {r['weight']:.0%})" for r in rows]
    return {"data": rows, "summary": "Upcoming deadlines: " + "; ".join(parts) + "."}


def find_free_rooms(ctx: ToolContext, args: FreeRoomArgs) -> dict:
    day = resolve_date(args.date, ctx.today)
    if minutes_between(args.start, args.end) <= 0:
        return {"ok": False, "error": "end time must be after start time", "summary": "Invalid time window."}
    rows = queries.free_rooms(_read(ctx), day, args.start, args.end, args.min_capacity, args.needs_projector,
                              args.needs_pcs)
    window = f"{day.isoformat()} ({queries.weekday_of(day).capitalize()}), {args.start}–{args.end}"
    if not rows:
        return {"data": {"date": day.isoformat(), "start": args.start, "end": args.end, "rooms": []},
                "summary": f"No free room matches for {window}."}
    names = ", ".join(f"{r['room_id']} ({r['capacity']} seats{', projector' if r['has_projector'] else ''}"
                      f"{', PCs' if r['has_pcs'] else ''})" for r in rows)
    return {"data": {"date": day.isoformat(), "start": args.start, "end": args.end, "rooms": rows},
            "summary": f"Free rooms for {window}: {names}."}


def check_book(ctx: ToolContext, args: BookArgs) -> dict:
    if not args.isbn and not args.title:
        return {"ok": False, "error": "give an ISBN or part of a title", "summary": "No ISBN or title given."}
    rows = queries.check_book(_read(ctx), args.isbn, args.title)
    if not rows:
        what = f"ISBN {args.isbn}" if args.isbn else f"a title containing '{args.title}'"
        return {"data": [], "summary": f"The campus library catalogue has no book with {what}.",
                "suggest": "search_books"}
    parts = []
    for r in rows:
        status = "on the shelf" if r["available"] > 0 else "all copies on loan"
        parts.append(f"'{r['title']}' (ISBN {r['isbn']}): {r['available']} of {r['copies_total']} copies available, "
                     f"{status}")
    return {"data": rows, "summary": "; ".join(parts) + "."}


def get_loans(ctx: ToolContext, args: NoArgs) -> dict:
    rows = queries.loans(_read(ctx), ctx.account_id)
    if not rows:
        return {"data": [], "summary": "The signed-in account has no active loans."}
    return {"data": rows, "summary": "Active loans: " + "; ".join(f"'{r['title']}' due {r['due_date']}" for r in rows) + "."}


def get_calendar(ctx: ToolContext, args: CalendarArgs) -> dict:
    start, end = resolve_date(args.date_from, ctx.today), resolve_date(args.date_to, ctx.today)
    if end < start:
        start, end = end, start
    rows = queries.calendar(_read(ctx), start, end, args.kind)
    if not rows:
        return {"data": [], "summary": f"No calendar entries between {start} and {end}."}
    parts = [f"{r['date']} {r['title']}" + (f" {r['start']}–{r['end']}" if r["start"] else "")
             + (f" at {r['location']}" if r["location"] else "") for r in rows]
    return {"data": rows, "summary": "Calendar: " + "; ".join(parts) + "."}


# ------------------------------------------------------------------- writes

def book_room(ctx: ToolContext, args: BookRoomArgs) -> dict:
    day = resolve_date(args.date, ctx.today)
    read = _read(ctx)
    problems = []
    if not queries.room_exists(read, args.room_id):
        problems.append(f"room {args.room_id} does not exist")
    length = minutes_between(args.start, args.end)
    if length <= 0 or length > MAX_BOOKING_MINUTES:
        problems.append(f"a booking lasts 1-{MAX_BOOKING_MINUTES} minutes (handbook section 11)")
    if not (ctx.today <= day <= ctx.today + dt.timedelta(days=MAX_DAYS_AHEAD)):
        problems.append(f"bookings are made up to {MAX_DAYS_AHEAD} days ahead")
    clashes = queries.room_clashes(read, args.room_id, day, args.start, args.end)
    if clashes:
        problems.append(f"room is taken: {clashes[0]['kind']} {clashes[0]['what']} {clashes[0]['start']}–{clashes[0]['end']}")
    active = [b for b in queries.bookings_for(read, ctx.account_id)
              if b["status"] == "confirmed" and b["date"] >= ctx.today.isoformat()]
    if len(active) >= MAX_ACTIVE_BOOKINGS:
        problems.append(f"at most {MAX_ACTIVE_BOOKINGS} active bookings per account")
    if problems:
        return {"ok": False, "error": "; ".join(problems), "summary": "Booking not made: " + "; ".join(problems) + "."}
    booking_id = queries.insert_booking(_write(ctx), ctx.account_id, args.room_id, day, args.start, args.end,
                                        args.purpose)
    return {"data": {"booking_id": booking_id, "room_id": args.room_id, "date": day.isoformat(), "start": args.start,
                     "end": args.end},
            "summary": f"Booked room {args.room_id} on {day.isoformat()}, {args.start}–{args.end} (booking {booking_id})."}


def place_hold(ctx: ToolContext, args: HoldArgs) -> dict:
    read = _read(ctx)
    rows = queries.check_book(read, args.isbn, None)
    if not rows:
        return {"ok": False, "error": f"ISBN {args.isbn} is not in the campus catalogue",
                "summary": f"No hold placed: ISBN {args.isbn} is not in the campus catalogue."}
    if rows[0]["available"] > 0:
        return {"ok": False, "error": "a copy is on the shelf; holds apply only when no copy is available",
                "summary": "No hold placed: a copy is on the shelf (handbook section 10)."}
    active = [h for h in queries.holds(read, ctx.account_id) if h["status"] == "active"]
    if len(active) >= MAX_ACTIVE_HOLDS:
        return {"ok": False, "error": f"at most {MAX_ACTIVE_HOLDS} active holds", "summary": "No hold placed: limit reached."}
    hold_id = queries.insert_hold(_write(ctx), ctx.account_id, args.isbn, ctx.now)
    return {"data": {"hold_id": hold_id, "isbn": args.isbn}, "summary": f"Hold {hold_id} placed on '{rows[0]['title']}'."}


def add_event(ctx: ToolContext, args: ExtractedEvent) -> dict:
    missing = [f for f in ("title", "date") if not getattr(args, f)]
    if missing:
        return {"ok": False, "error": f"missing {', '.join(missing)}", "summary": f"Event not added: missing {', '.join(missing)}."}
    date = resolve_date(args.date, ctx.today).isoformat()
    start = normalize_time(args.start) if args.start else None
    end = normalize_time(args.end) if args.end else None
    event_id = queries.insert_event(_write(ctx), args.title, date, start, end, args.location, "event", "image")
    return {"data": {"event_id": event_id, "title": args.title, "date": date, "start": start, "end": end,
                     "location": args.location},
            "summary": f"Added '{args.title}' on {date}" + (f", {start}–{end}" if start else "")
                       + (f" at {args.location}" if args.location else "") + f" (event {event_id})."}


SPECS = [
    ToolSpec("search_handbook", "Search the approved handbook and course documents; returns cited passages.",
             SearchArgs, search_handbook, kind="rag", source="chunk store"),
    ToolSpec("get_timetable", "Timetable of the signed-in account's courses: day, time, and room of each session.",
             TimetableArgs, get_timetable, source="sessions"),
    ToolSpec("get_deadlines", "Upcoming assignment deadlines of the signed-in account's courses.", DeadlineArgs,
             get_deadlines, source="assignments"),
    ToolSpec("find_free_rooms", "Rooms with no session or booking in a time window, filtered by seats and equipment.",
             FreeRoomArgs, find_free_rooms, source="rooms, room_bookings, sessions"),
    ToolSpec("check_book", "Campus library catalogue lookup by ISBN or title, with copies available.", BookArgs,
             check_book, source="books, loans"),
    ToolSpec("get_loans", "Active library loans of the signed-in account.", NoArgs, get_loans, source="loans"),
    ToolSpec("get_calendar", "Campus events, holidays, seminars, and exam weeks between two dates.", CalendarArgs,
             get_calendar, source="events"),
    ToolSpec("book_room", "Book a room for the signed-in account. Needs confirmation.", BookRoomArgs, book_room,
             write=True, source="room_bookings"),
    ToolSpec("place_hold", "Place a library hold for the signed-in account. Needs confirmation.", HoldArgs,
             place_hold, write=True, source="holds"),
    ToolSpec("add_event", "Add an event to the campus calendar. Needs confirmation.", ExtractedEvent, add_event,
             write=True, source="events"),
]
