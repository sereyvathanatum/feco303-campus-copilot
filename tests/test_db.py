import datetime as dt
import sqlite3

import pytest

from campus_copilot.config import DATA_DIR
from campus_copilot.db import connection, queries, seed


@pytest.fixture
def db(tmp_path):
    return seed.build(tmp_path / "campus.db")


def test_seed_is_reproducible(tmp_path):
    first = seed.content_hash(seed.build(tmp_path / "a.db"))
    second = seed.content_hash(seed.build(tmp_path / "b.db"))
    assert first == second
    recorded = (DATA_DIR / "seed" / "seed.sha256").read_text(encoding="utf-8").split()[0]
    assert first == recorded, "seed CSVs changed: rerun `cli seed` and update data/seed/seed.sha256"


def test_every_table_has_rows(db):
    counts = seed.table_counts(db)
    assert counts["accounts"] == 20
    assert all(n > 0 for n in counts.values())


@pytest.mark.parametrize("sql", [
    "DELETE FROM loans",
    "UPDATE loans SET returned = 1",
    "INSERT INTO holds (isbn, account_id, created_at) VALUES ('x', 'A0001', 'now')",
    "DROP TABLE loans",
    "CREATE TABLE t (x)",
    "PRAGMA table_info(loans)",
    "ATTACH DATABASE ':memory:' AS other",
])
def test_read_connection_denies_non_select(db, sql):
    conn = connection.read_connection(db)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute(sql)
    assert conn.authorizer_log.denials


def test_read_connection_denies_accounts_table(db):
    conn = connection.read_connection(db)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("SELECT display_name FROM accounts")
    assert "accounts table" in conn.authorizer_log.denials[-1]


def test_read_connection_denies_unlisted_tables_and_columns(db):
    conn = connection.read_connection(db, allow={"books": {"isbn", "title"}})
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("SELECT * FROM loans")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("SELECT authors FROM books")
    assert conn.execute("SELECT title FROM books WHERE isbn = '9780262046305'").fetchone()


def test_read_connection_denies_sqlite_master(db):
    conn = connection.read_connection(db)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("SELECT sql FROM sqlite_master")


def test_write_connection_limits_tables(db):
    conn = connection.write_connection(db)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM room_bookings")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE loans SET returned = 1")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("INSERT INTO accounts VALUES ('A9999', 'x', 'y')")
    booking = queries.insert_booking(conn, "A0001", "B-204", dt.date(2026, 10, 7), "14:00", "16:00", "study")
    assert booking > 0


def test_templates_never_return_other_accounts(db):
    conn = connection.read_connection(db)
    for account in ("A0001", "A0007"):
        assert all(r["course_code"] in queries.enrolled_courses(conn, account)
                   for r in queries.timetable(conn, account))
        own = {r["isbn"] for r in queries.loans(conn, account)}
        raw = sqlite3.connect(db).execute(
            "SELECT isbn FROM loans WHERE account_id = ? AND returned = 0", (account,)).fetchall()
        assert own == {r[0] for r in raw}
    a1 = {(r["isbn"], r["due_date"]) for r in queries.loans(conn, "A0001")}
    a7 = {(r["isbn"], r["due_date"]) for r in queries.loans(conn, "A0007")}
    assert a1.isdisjoint(a7)


def test_demo_facts(db):
    conn = connection.read_connection(db)
    lab = queries.timetable(conn, "A0001", course="FECO303")
    assert any(r["kind"] == "lab" and r["weekday"] == "thursday" and r["room_id"] == "C-301" for r in lab)
    book = queries.check_book(conn, isbn="9780262046305")[0]
    assert book["available"] == 1
    rooms = queries.free_rooms(conn, dt.date(2026, 10, 7), "14:00", "16:00", needs_projector=True)
    ids = [r["room_id"] for r in rooms]
    assert ids and "A-101" not in ids and "B-201" not in ids and "D-101" not in ids
    assert all(r["has_projector"] for r in rooms)


def test_display_name_comes_from_app_code(db):
    assert connection.account_display_name("A0001", db) == "Sok Dara"
