"""Notice reader: synthetic images, field checks, blanking, and the confirm-before-write path."""

from __future__ import annotations

import json

from steps.conftest import offline_copilot

from campus_copilot import config
from campus_copilot.db import connection, queries
from campus_copilot.evaluation.vision import run_vision_eval
from campus_copilot.multimodal.notice_reader import normalize_event

IMAGES = config.DATA_DIR / "images"


def test_images_and_manifest_exist():
    manifest = json.loads((IMAGES / "manifest.json").read_text(encoding="utf-8"))
    assert {"poster_clean.png", "poster_blurred.png", "poster_rotated.png", "poster_khmer.png",
            "timetable_dense.png"} <= set(manifest)
    assert all((IMAGES / name).is_file() for name in manifest)


def test_normalize_event():
    event = normalize_event({"title": "Seminar", "date": "Friday 16 October 2026", "start": "4 pm", "end": "17.30",
                             "location": "Room A-101, Building A"}, config.today())
    assert event == {"title": "Seminar", "date": "2026-10-16", "start": "16:00", "end": "17:30", "location": "A-101"}


def test_clean_poster_becomes_a_confirmed_event(pack_env):
    copilot = offline_copilot(12)
    try:
        conn = connection.read_connection()
        before = len(queries.calendar(conn, config.today(), config.today().replace(month=12)))
        pending = copilot.ask("Add this to the calendar.", thread_id="p", image_path=str(IMAGES / "poster_clean.png"))
        assert pending.kind == "confirm" and pending.pending_write["tool"] == "add_event"
        assert len(queries.calendar(connection.read_connection(), config.today(), config.today().replace(month=12))) == before
        done = copilot.resume("p", confirm=True)
        assert done.tool_calls[-1]["ok"] and "2026-10-16" in done.answer
        events = queries.calendar(connection.read_connection(), config.today(), config.today().replace(month=12))
        assert len(events) == before + 1 and any(e["source"] == "image" for e in events)
    finally:
        copilot.close()


def test_blurred_and_rotated_posters_are_flagged(pack_env):
    copilot = offline_copilot(12)
    try:
        blurred = copilot.ask("Add this to the calendar.", image_path=str(IMAGES / "poster_blurred.png"))
        rotated = copilot.ask("Add this to the calendar.", image_path=str(IMAGES / "poster_rotated.png"))
        assert blurred.kind == "clarify" and "start" in blurred.answer
        assert rotated.kind == "clarify" and "location" in rotated.answer
        assert not blurred.pending_write and not rotated.pending_write
    finally:
        copilot.close()


def test_vision_eval_reports_every_image(pack_env):
    copilot = offline_copilot(12)
    try:
        rows = {r["image"]: r for r in run_vision_eval(copilot.rt)}
        assert rows["poster_clean.png"]["field_accuracy"] == 1.0 and not rows["poster_clean.png"]["flagged"]
        assert rows["poster_blurred.png"]["flagged"] and rows["poster_khmer.png"]["flagged"] == ["date"]
        assert all(not r["wrong_and_unflagged"] or r["image"] == "timetable_dense.png" for r in rows.values())
    finally:
        copilot.close()
