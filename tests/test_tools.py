"""Tools: registry contract, campus DB tools, public-API tools; success, empty, error, and timeout, all offline."""

from __future__ import annotations

import datetime as dt

import pytest
import requests
from fakes import FakeResponse, RecordingSession

from campus_copilot import config
from campus_copilot.db import connection, queries
from campus_copilot.tools import text_to_sql
from campus_copilot.tools.http import HttpClient
from campus_copilot.tools.registry import ToolContext, registry

TODAY = dt.date(2026, 10, 6)


@pytest.fixture
def ctx(runs_dir):
    settings = config.get_settings("offline")
    connection.ensure_seeded()
    return ToolContext.create(settings, "A0001")


def live_ctx(runs_dir, session) -> ToolContext:
    settings = config.get_settings("offline")
    connection.ensure_seeded()
    return ToolContext.create(settings, "A0001", http=HttpClient(settings, live=True, session=session))


def run(ctx, name, args=None, allow_write=False):
    return registry().run(name, args or {}, ctx, allow_write=allow_write)


# ------------------------------------------------------------------ registry

def test_schemas_are_identical_across_native_json_and_mcp():
    for spec in registry().specs(include_sql=True):
        native = spec.native_schema()["function"]["parameters"]
        assert native == spec.json_protocol()["args"] == spec.mcp_schema()["inputSchema"]
        assert "account_id" not in native.get("properties", {})


def test_errors_are_data(ctx):
    assert run(ctx, "teleport")["ok"] is False
    bad = run(ctx, "find_free_rooms", {"date": "tomorrow"})
    assert bad["ok"] is False and "invalid arguments" in bad["error"]
    assert run(ctx, "get_loans", {"account_id": "A0007"})["ok"] is False
    assert "confirmation" in run(ctx, "book_room", {"room_id": "B-204", "date": "tomorrow", "start": "14:00",
                                                    "end": "16:00"})["error"]


def test_the_clock_is_pinned_in_tests(ctx):
    assert ctx.today == TODAY


# --------------------------------------------------------------- campus reads

def test_timetable_success_and_empty(ctx):
    ok = run(ctx, "get_timetable", {"course": "FECO303"})
    assert ok["ok"] and any(r["room_id"] == "C-301" and r["kind"] == "lab" for r in ok["data"])
    assert "2026-10-08" in ok["summary"]
    empty = run(ctx, "get_timetable", {"course": "FECS999"})
    assert empty["ok"] and empty["data"] == [] and "not among the enrolled courses" in empty["summary"]


def test_deadlines_and_calendar(ctx):
    assert run(ctx, "get_deadlines", {"course": "FECO303"})["data"]
    assert run(ctx, "get_deadlines", {"within_days": 0})["data"] == []
    cal = run(ctx, "get_calendar", {"from": "2026-10-01", "to": "2026-10-31"})
    assert any(r["kind"] == "holiday" for r in cal["data"])


def test_free_rooms_and_invalid_window(ctx):
    rooms = run(ctx, "find_free_rooms", {"date": "tomorrow", "start": "2 pm", "end": "4 pm", "needs_projector": True})
    ids = [r["room_id"] for r in rooms["data"]["rooms"]]
    assert ids and "A-101" not in ids and rooms["data"]["start"] == "14:00"
    assert run(ctx, "find_free_rooms", {"date": "tomorrow", "start": "16:00", "end": "14:00"})["ok"] is False


def test_books_and_loans(ctx):
    book = run(ctx, "check_book", {"isbn": "9780262046305"})
    assert "on the shelf" in book["summary"] and book["data"][0]["available"] == 1
    missing = run(ctx, "check_book", {"title": "nonexistent title"})
    assert missing["data"] == [] and missing["suggest"] == "search_books"
    loans = run(ctx, "get_loans")
    assert loans["ok"] and len(loans["data"]) == 2


# ------------------------------------------------------------- campus writes

def test_book_room_writes_after_confirmation_and_checks_rules(ctx):
    conn = connection.read_connection()
    before = len(queries.bookings_for(conn, "A0001"))
    ok = run(ctx, "book_room", {"room_id": "B-204", "date": "tomorrow", "start": "14:00", "end": "16:00"},
             allow_write=True)
    assert ok["ok"], ok
    assert len(queries.bookings_for(connection.read_connection(), "A0001")) == before + 1
    clash = run(ctx, "book_room", {"room_id": "B-204", "date": "tomorrow", "start": "15:00", "end": "16:00"},
                allow_write=True)
    assert clash["ok"] is False and "taken" in clash["error"]
    too_long = run(ctx, "book_room", {"room_id": "B-203", "date": "tomorrow", "start": "08:00", "end": "11:00"},
                   allow_write=True)
    assert too_long["ok"] is False and "minutes" in too_long["error"]


def test_hold_only_when_no_copy_is_available(ctx):
    on_shelf = run(ctx, "place_hold", {"isbn": "9780262046305"}, allow_write=True)
    assert on_shelf["ok"] is False
    assert run(ctx, "place_hold", {"isbn": "9780134685991"}, allow_write=True)["ok"]


def test_add_event_needs_title_and_date(ctx):
    assert run(ctx, "add_event", {"title": "Seminar", "date": "2026-10-15", "start": "16:00", "end": "17:30",
                                  "location": "A-101"}, allow_write=True)["ok"]
    assert run(ctx, "add_event", {"title": "No date"}, allow_write=True)["ok"] is False


# ----------------------------------------------------------------- public APIs

API_CALLS = [
    ("campus_weather", {"date": "tomorrow", "hour": "2 pm", "until": "4 pm"}),
    ("convert_currency", {"amount": 20, "direction": "usd_to_khr"}),
    ("search_books", {"query": "deep learning"}),
    ("concept_summary", {"topic": "attention"}),
]


@pytest.mark.parametrize("name,args", API_CALLS)
def test_api_tools_replay_fixtures_with_attribution(ctx, name, args):
    result = run(ctx, name, args)
    assert result["ok"], result
    assert result["attribution"] and result["fetched_at"] is not None and result["source"].startswith("fixture")


def test_weather_fixture_is_redated_to_the_campus_date(ctx):
    result = run(ctx, "campus_weather", {"date": "tomorrow"})
    assert result["source"] == "fixture (re-dated)" or result["data"]["date"] == "2026-10-07"
    assert all(h["time"].startswith("2026-10-07") for h in result["data"]["hours"])


def test_currency_both_directions(ctx):
    usd = run(ctx, "convert_currency", {"amount": 20, "direction": "usd_to_khr"})
    khr = run(ctx, "convert_currency", {"amount": usd["data"]["result"], "direction": "khr_to_usd"})
    assert abs(khr["data"]["result"] - 20) < 0.05
    assert usd["data"]["result_at_fixed_rate"] == 82000


def test_concept_summary_is_marked_untrusted(ctx):
    result = run(ctx, "concept_summary", {"topic": "attention"})
    assert result["untrusted"] and result["summary"].startswith("External source (Wikipedia")


@pytest.mark.parametrize("name,args", API_CALLS)
def test_api_tools_report_timeouts_as_data(runs_dir, monkeypatch, name, args):
    monkeypatch.setattr("campus_copilot.tools.http.RETRIES", 0)
    monkeypatch.setattr(HttpClient, "clock_pinned", property(lambda self: False))
    ctx = live_ctx(runs_dir, RecordingSession(default=requests.Timeout("slow")))
    result = run(ctx, name, args)
    assert result["ok"] is False and "timeout" in result["error"]


@pytest.mark.parametrize("name,args", API_CALLS)
def test_api_tools_report_http_errors_as_data(runs_dir, monkeypatch, name, args):
    monkeypatch.setattr("campus_copilot.tools.http.RETRIES", 0)
    monkeypatch.setattr(HttpClient, "clock_pinned", property(lambda self: False))
    ctx = live_ctx(runs_dir, RecordingSession(default=FakeResponse(500, text="boom")))
    result = run(ctx, name, args)
    assert result["ok"] is False and "HTTP 500" in result["error"]


def test_api_tools_send_the_user_agent_with_contact(runs_dir):
    session = RecordingSession(default=FakeResponse(200, {"docs": []}))
    ctx = live_ctx(runs_dir, session)
    empty = run(ctx, "search_books", {"query": "no such book"})
    assert empty["ok"] and empty["data"] == [] and "no match" in empty["summary"]
    assert session.requests[0]["headers"]["User-Agent"].startswith("FECO303-CampusCopilot/1.0 (+")


def test_missing_fixture_is_an_error(runs_dir, tmp_path):
    settings = config.get_settings("offline")
    connection.ensure_seeded()
    ctx = ToolContext.create(settings, "A0001", http=HttpClient(settings, live=False, fixtures_dir=tmp_path))
    assert run(ctx, "convert_currency", {"amount": 1, "direction": "usd_to_khr"})["ok"] is False


def test_poisoned_variant_is_used_only_when_asked(runs_dir):
    settings = config.get_settings("offline", {"apis.fixture_variant": "poisoned"})
    connection.ensure_seeded()
    ctx = ToolContext.create(settings, "A0001")
    assert "ignore previous instructions" in run(ctx, "concept_summary", {"topic": "attention"})["data"]["extract"]


# ------------------------------------------------------------- text-to-SQL

def test_text_to_sql_sandbox_stops_bad_queries(ctx):
    ok = run(ctx, "run_sql", {"sql": "SELECT id, capacity FROM rooms WHERE has_projector = 1"})
    assert ok["ok"] and ok["data"]["rows"]
    drop = run(ctx, "run_sql", {"sql": "'; DROP TABLE loans;--"})
    assert drop["ok"] is False
    other = run(ctx, "run_sql", {"sql": "SELECT isbn FROM loans WHERE account_id = 'A0007'"})
    assert other["ok"] is False and "loans.account_id" in other["data"]["stopped_by"]
    assert run(ctx, "run_sql", {"sql": "DELETE FROM loans"})["ok"] is False
    many = run(ctx, "run_sql", {"sql": "SELECT a.id FROM rooms a, rooms b, rooms c"})
    assert many["ok"] and many["data"]["capped"] and len(many["data"]["rows"]) == text_to_sql.ROW_CAP


def test_pinned_clock_replays_the_forecast_even_when_live(runs_dir):
    ctx = live_ctx(runs_dir, RecordingSession(default=requests.Timeout("never called")))
    result = run(ctx, "campus_weather", {"date": "tomorrow"})
    assert result["ok"] and "campus clock pinned" in result["source"]
