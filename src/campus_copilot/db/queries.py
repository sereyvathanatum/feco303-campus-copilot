"""Parameterised query templates. No string-formatted SQL lives here.

Every account-scoped template takes `account_id` from session state; no template
accepts an account ID chosen by a model.
"""

from __future__ import annotations

import datetime as dt
import sqlite3

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def weekday_of(date: dt.date) -> str:
    return WEEKDAYS[date.weekday()]


def _rows(cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


# ------------------------------------------------------------------------ reads

def enrolled_courses(conn: sqlite3.Connection, account_id: str) -> list[str]:
    cur = conn.execute("SELECT course_code FROM enrollments WHERE account_id = ? ORDER BY course_code", (account_id,))
    return [r["course_code"] for r in cur.fetchall()]


def course_codes(conn: sqlite3.Connection) -> list[dict]:
    return _rows(conn.execute("SELECT code, title FROM courses ORDER BY code"))


def timetable(conn: sqlite3.Connection, account_id: str, course: str | None = None,
              weekday: str | None = None) -> list[dict]:
    return _rows(conn.execute(
        """
        SELECT s.course_code, c.title, s.weekday, s.start, s."end", s.room_id, s.kind
        FROM sessions s
        JOIN enrollments e ON e.course_code = s.course_code
        JOIN courses c ON c.code = s.course_code
        WHERE e.account_id = :account
          AND (:course IS NULL OR s.course_code = :course)
          AND (:weekday IS NULL OR s.weekday = :weekday)
        ORDER BY CASE s.weekday WHEN 'monday' THEN 1 WHEN 'tuesday' THEN 2 WHEN 'wednesday' THEN 3
                 WHEN 'thursday' THEN 4 WHEN 'friday' THEN 5 WHEN 'saturday' THEN 6 ELSE 7 END, s.start
        """,
        {"account": account_id, "course": course, "weekday": weekday},
    ))


def deadlines(conn: sqlite3.Connection, account_id: str, now: dt.datetime, course: str | None = None,
              within_days: int | None = None) -> list[dict]:
    until = (now + dt.timedelta(days=within_days)).strftime("%Y-%m-%d %H:%M") if within_days is not None else None
    return _rows(conn.execute(
        """
        SELECT a.course_code, a.title, a.due_at, a.weight
        FROM assignments a
        JOIN enrollments e ON e.course_code = a.course_code
        WHERE e.account_id = :account
          AND a.due_at >= :now
          AND (:until IS NULL OR a.due_at <= :until)
          AND (:course IS NULL OR a.course_code = :course)
        ORDER BY a.due_at
        """,
        {"account": account_id, "now": now.strftime("%Y-%m-%d %H:%M"), "until": until, "course": course},
    ))


def free_rooms(conn: sqlite3.Connection, date: dt.date, start: str, end: str, min_capacity: int | None = None,
               needs_projector: bool | None = None, needs_pcs: bool | None = None) -> list[dict]:
    """Rooms with no session (by weekday) and no confirmed booking (by date) overlapping [start, end)."""
    return _rows(conn.execute(
        """
        SELECT r.id AS room_id, r.building, r.capacity, r.has_projector, r.has_pcs
        FROM rooms r
        WHERE (:min_capacity IS NULL OR r.capacity >= :min_capacity)
          AND (:projector IS NULL OR :projector = 0 OR r.has_projector = 1)
          AND (:pcs IS NULL OR :pcs = 0 OR r.has_pcs = 1)
          AND NOT EXISTS (
              SELECT 1 FROM sessions s
              WHERE s.room_id = r.id AND s.weekday = :weekday AND s.start < :end AND :start < s."end")
          AND NOT EXISTS (
              SELECT 1 FROM room_bookings b
              WHERE b.room_id = r.id AND b.date = :date AND b.status = 'confirmed'
                AND b.start < :end AND :start < b."end")
        ORDER BY r.capacity, r.id
        """,
        {"min_capacity": min_capacity, "projector": None if needs_projector is None else int(needs_projector),
         "pcs": None if needs_pcs is None else int(needs_pcs), "weekday": weekday_of(date),
         "date": date.isoformat(), "start": start, "end": end},
    ))


def room_clashes(conn: sqlite3.Connection, room_id: str, date: dt.date, start: str, end: str) -> list[dict]:
    sessions = _rows(conn.execute(
        """SELECT 'session' AS kind, course_code AS what, start, "end" FROM sessions
           WHERE room_id = ? AND weekday = ? AND start < ? AND ? < "end" """,
        (room_id, weekday_of(date), end, start)))
    bookings = _rows(conn.execute(
        """SELECT 'booking' AS kind, purpose AS what, start, "end" FROM room_bookings
           WHERE room_id = ? AND date = ? AND status = 'confirmed' AND start < ? AND ? < "end" """,
        (room_id, date.isoformat(), end, start)))
    return sessions + bookings


def room_exists(conn: sqlite3.Connection, room_id: str) -> bool:
    return conn.execute("SELECT 1 FROM rooms WHERE id = ?", (room_id,)).fetchone() is not None


def check_book(conn: sqlite3.Connection, isbn: str | None = None, title: str | None = None) -> list[dict]:
    return _rows(conn.execute(
        """
        SELECT b.isbn, b.title, b.authors, b.year, b.copies_total,
               b.copies_total - (SELECT count(*) FROM loans l WHERE l.isbn = b.isbn AND l.returned = 0) AS available
        FROM books b
        WHERE (:isbn IS NULL OR b.isbn = :isbn)
          AND (:title IS NULL OR lower(b.title) LIKE '%' || lower(:title) || '%')
        ORDER BY b.title
        LIMIT 10
        """,
        {"isbn": isbn, "title": title},
    ))


def loans(conn: sqlite3.Connection, account_id: str) -> list[dict]:
    return _rows(conn.execute(
        """SELECT l.isbn, b.title, l.due_date FROM loans l JOIN books b ON b.isbn = l.isbn
           WHERE l.account_id = ? AND l.returned = 0 ORDER BY l.due_date""",
        (account_id,)))


def holds(conn: sqlite3.Connection, account_id: str) -> list[dict]:
    return _rows(conn.execute(
        "SELECT id, isbn, created_at, status FROM holds WHERE account_id = ? ORDER BY created_at", (account_id,)))


def calendar(conn: sqlite3.Connection, date_from: dt.date, date_to: dt.date, kind: str | None = None) -> list[dict]:
    return _rows(conn.execute(
        """SELECT id, title, date, start, "end", location, kind, source FROM events
           WHERE date BETWEEN ? AND ? AND (? IS NULL OR kind = ?) ORDER BY date, start""",
        (date_from.isoformat(), date_to.isoformat(), kind, kind)))


def bookings_for(conn: sqlite3.Connection, account_id: str) -> list[dict]:
    return _rows(conn.execute(
        """SELECT id, room_id, date, start, "end", purpose, status FROM room_bookings
           WHERE account_id = ? ORDER BY date, start""", (account_id,)))


# ----------------------------------------------------------------------- writes

def insert_booking(conn: sqlite3.Connection, account_id: str, room_id: str, date: dt.date, start: str, end: str,
                   purpose: str) -> int:
    cur = conn.execute(
        """INSERT INTO room_bookings (room_id, date, start, "end", account_id, purpose, status)
           VALUES (?, ?, ?, ?, ?, ?, 'confirmed')""",
        (room_id, date.isoformat(), start, end, account_id, purpose))
    conn.commit()
    return int(cur.lastrowid)


def insert_hold(conn: sqlite3.Connection, account_id: str, isbn: str, created_at: dt.datetime) -> int:
    cur = conn.execute("INSERT INTO holds (isbn, account_id, created_at, status) VALUES (?, ?, ?, 'active')",
                       (isbn, account_id, created_at.strftime("%Y-%m-%d %H:%M")))
    conn.commit()
    return int(cur.lastrowid)


def insert_event(conn: sqlite3.Connection, title: str, date: str, start: str | None, end: str | None,
                 location: str | None, kind: str = "event", source: str = "image") -> int:
    cur = conn.execute(
        """INSERT INTO events (title, date, start, "end", location, kind, source) VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (title, date, start, end, location, kind, source))
    conn.commit()
    return int(cur.lastrowid)
