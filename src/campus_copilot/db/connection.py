"""Two connections to the campus database (docs/implementation-plan.md §8.5).

* The **read connection** opens the file with `mode=ro` and installs an authorizer
  that allows only `SELECT` over an allow-listed set of tables and columns. The
  `accounts` table is denied outright, because the authorizer works per column,
  not per row; row scoping to `session.account_id` lives in the query templates.
* The **write connection** allows `INSERT`/`UPDATE` only on `room_bookings`,
  `holds`, and `events`. Only the three write tools use it, after confirmation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import config
from . import seed

READ_ALLOW: dict[str, set[str]] = {
    "courses": {"code", "title", "credits"},
    "enrollments": {"account_id", "course_code"},
    "rooms": {"id", "building", "capacity", "has_projector", "has_pcs"},
    "sessions": {"course_code", "weekday", "start", "end", "room_id", "kind"},
    "room_bookings": {"id", "room_id", "date", "start", "end", "account_id", "purpose", "status"},
    "books": {"isbn", "title", "authors", "year", "copies_total"},
    "loans": {"isbn", "account_id", "due_date", "returned"},
    "holds": {"id", "isbn", "account_id", "created_at", "status"},
    "assignments": {"course_code", "title", "due_at", "weight"},
    "events": {"id", "title", "date", "start", "end", "location", "kind", "source"},
}
WRITE_TABLES = {"room_bookings", "holds", "events"}
DENIED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer"}


class AuthorizerLog:
    """Records the last denial so tools and E07 can report which rule stopped a query."""

    def __init__(self) -> None:
        self.denials: list[str] = []

    def deny(self, reason: str) -> int:
        self.denials.append(reason)
        return sqlite3.SQLITE_DENY


class CampusConnection(sqlite3.Connection):
    """A connection that carries its authorizer log."""

    authorizer_log: AuthorizerLog


def _action_name(code: int) -> str:
    for name in dir(sqlite3):
        if name.startswith("SQLITE_") and getattr(sqlite3, name) == code and name not in {
            "SQLITE_OK", "SQLITE_DENY", "SQLITE_IGNORE"}:
            return name
    return str(code)


def read_authorizer(log: AuthorizerLog, allow: dict[str, set[str]] | None = None):
    allow = allow or READ_ALLOW

    def authorize(action, arg1, arg2, dbname, source):
        if action == sqlite3.SQLITE_SELECT:
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            table, column = arg1, arg2
            if table == "accounts":
                return log.deny("rule: the accounts table is never readable through this connection")
            if table not in allow:
                return log.deny(f"rule: table '{table}' is not on the read allow-list")
            if column and column not in allow[table]:
                return log.deny(f"rule: column '{table}.{column}' is not on the read allow-list")
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            if (arg2 or "").lower() in DENIED_FUNCTIONS:
                return log.deny(f"rule: function '{arg2}' is denied")
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_RECURSIVE:
            return sqlite3.SQLITE_OK
        return log.deny(f"rule: only SELECT is allowed (statement tried {_action_name(action)})")

    return authorize


def write_authorizer(log: AuthorizerLog):
    def authorize(action, arg1, arg2, dbname, source):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_FUNCTION):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if arg1 == "accounts":
                return log.deny("rule: the accounts table is never readable through this connection")
            return sqlite3.SQLITE_OK if arg1 in READ_ALLOW or arg1 == "sqlite_sequence" else log.deny(
                f"rule: table '{arg1}' is not readable")
        if action in (sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE):
            if arg1 in WRITE_TABLES or arg1 == "sqlite_sequence":
                return sqlite3.SQLITE_OK
            return log.deny(f"rule: writes are allowed only on {sorted(WRITE_TABLES)}, not '{arg1}'")
        return log.deny(f"rule: write connection allows only INSERT/UPDATE (tried {_action_name(action)})")

    return authorize


def db_path() -> Path:
    return config.runs_dir() / "campus.db"


def ensure_seeded(path: Path | None = None) -> Path:
    path = path or db_path()
    if not path.exists():
        seed.build(path)
    return path


def read_connection(path: Path | None = None, allow: dict[str, set[str]] | None = None) -> CampusConnection:
    path = ensure_seeded(path)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, check_same_thread=False,
                           factory=CampusConnection)
    conn.row_factory = sqlite3.Row
    conn.authorizer_log = AuthorizerLog()
    conn.set_authorizer(read_authorizer(conn.authorizer_log, allow))
    return conn


def write_connection(path: Path | None = None) -> CampusConnection:
    path = ensure_seeded(path)
    conn = sqlite3.connect(path, check_same_thread=False, factory=CampusConnection)
    conn.row_factory = sqlite3.Row
    conn.authorizer_log = AuthorizerLog()
    conn.set_authorizer(write_authorizer(conn.authorizer_log))
    return conn


def account_display_name(account_id: str, path: Path | None = None) -> str | None:
    """App-code lookup of the signed-in account's display name. Never exposed to a model."""
    path = ensure_seeded(path)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT display_name FROM accounts WHERE id = ?", (account_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def list_account_ids(path: Path | None = None) -> list[str]:
    path = ensure_seeded(path)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return [r[0] for r in conn.execute("SELECT id FROM accounts ORDER BY id")]
    finally:
        conn.close()
