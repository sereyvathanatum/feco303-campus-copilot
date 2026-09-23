"""Generate synthetic notice images for the vision step and E14 (data/images/).

Variants: a clean poster, blurred, rotated, a Khmer-script poster, and a dense
timetable photo. No real people or documents appear. `manifest.json` records, per
image, the ground truth and the reading that the offline stub model returns (a
typical failure for that variant), so offline runs show the same failure types a
live vision model tends to produce.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "images"
KHMER_FONT = ROOT / "data" / "sources" / "_src" / "fonts" / "NotoSansKhmer-Regular.ttf"
KHMER_RUN = re.compile(r"[ក-៿᧠-᧿\s]+")
SCRIPT_RUNS = re.compile(r"[ក-៿᧠-᧿]+(?:\s+[ក-៿᧠-᧿]+)*|[^ក-៿᧠-᧿]+")

EVENT = {"title": "AI Seminar: Khmer Speech Recognition in Practice", "date": "2026-10-16", "start": "16:00",
         "end": "17:30", "location": "A-101"}
POSTER_LINES = ["CamTech AI Seminar", "Khmer Speech Recognition in Practice", "", "Friday 16 October 2026",
                "16:00 - 17:30", "Room A-101, Building A", "", "Free entry - demo poster, synthetic event"]
TRANSCRIPTION = "\n".join(line for line in POSTER_LINES if line)


def font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def poster(lines: list[str], sizes: list[int], path: Path, khmer: bool = False) -> Image.Image:
    img = Image.new("RGB", (1000, 1400), (250, 246, 236))
    draw = ImageDraw.Draw(img)
    draw.rectangle([40, 40, 960, 1360], outline=(30, 60, 110), width=8)
    draw.rectangle([40, 40, 960, 340], fill=(30, 60, 110))
    y = 90
    for index, (line, size) in enumerate(zip(lines, sizes)):
        if not line:
            y += 40
            continue
        colour = (255, 255, 255) if index < 2 else (20, 20, 30)
        # Khmer runs use the Khmer font; digits and Latin letters use the default font (Noto Sans Khmer has no Latin)
        runs = [(m.group(0), ImageFont.truetype(str(KHMER_FONT), size) if khmer and KHMER_RUN.fullmatch(m.group(0))
                 else font(size)) for m in SCRIPT_RUNS.finditer(line)]
        x = (1000 - sum(draw.textlength(text, font=face) for text, face in runs)) / 2
        for text, face in runs:
            draw.text((x, y), text, fill=colour, font=face)
            x += draw.textlength(text, font=face)
        y += size + (70 if index < 2 else 40)
        if index == 1:
            y = max(y, 400)
    img.save(path)
    return img


def timetable(path: Path) -> None:
    rows = [["Time", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            ["08:00", "FECO303 A-101", "FECS329 A-102", "FECO301 C-302", "FESE305 B-201", "FEGE201 B-203"],
            ["09:45", "-", "-", "-", "-", "FECS329 C-302"],
            ["13:30", "FESE308 B-201", "FECO301 D-101", "FESE308 C-301", "FECO303 C-301", "FESE311 C-301"],
            ["14:00", "-", "-", "FESE311 A-101", "-", "-"],
            ["14:30", "-", "-", "FESE305 A-102", "-", "-"]]
    img = Image.new("RGB", (1500, 760), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    face, head = font(26), font(30)
    draw.text((30, 20), "Week timetable (demo, synthetic)", fill=(0, 0, 0), font=head)
    col_w, row_h = 240, 100
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            x, y = 30 + c * col_w, 80 + r * row_h
            draw.rectangle([x, y, x + col_w, y + row_h], outline=(90, 90, 90), width=2)
            draw.text((x + 10, y + 34), cell, fill=(0, 0, 0), font=face)
    img = img.rotate(3, expand=True, fillcolor=(235, 235, 235)).filter(ImageFilter.GaussianBlur(1.2))
    img.save(path)


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [54, 46, 0, 44, 60, 40, 0, 26]
    clean = poster(POSTER_LINES, sizes, OUT / "poster_clean.png")
    clean.filter(ImageFilter.GaussianBlur(4)).save(OUT / "poster_blurred.png")
    clean.rotate(14, expand=True, fillcolor=(200, 200, 200)).save(OUT / "poster_rotated.png")
    khmer_lines = ["CamTech AI Seminar", "សិក្ខាសាលា AI",
                   "", "ថ្ងៃសុក្រ ទី១៦ តុលា ២០២៦",
                   "16:00 - 17:30", "បន្ទប់ A-101", "", "demo poster, synthetic event"]
    poster(khmer_lines, sizes, OUT / "poster_khmer.png", khmer=True)
    timetable(OUT / "timetable_dense.png")
    shaping = "with complex-script shaping" if features.check("raqm") else \
        "without complex-script shaping (Pillow built without raqm), so Khmer glyphs may be misordered"
    manifest = {
        "poster_clean.png": {"variant": "clean", "truth": {"transcription": TRANSCRIPTION, "event": EVENT},
                             "stub_reading": {"transcription": TRANSCRIPTION, "event": EVENT}},
        "poster_blurred.png": {"variant": "blur", "truth": {"transcription": TRANSCRIPTION, "event": EVENT},
                               "stub_reading": {"transcription": TRANSCRIPTION.replace("16:00 - 17:30", "18:00 - 17:30"),
                                                "event": {**EVENT, "start": "18:00"}},
                               "failure": "blur hides digits: the start time is misread"},
        "poster_rotated.png": {"variant": "rotation", "truth": {"transcription": TRANSCRIPTION, "event": EVENT},
                               "stub_reading": {"transcription": TRANSCRIPTION.replace("Room A-101, Building A", ""),
                                                "event": {**EVENT, "location": "B-101"}},
                               "failure": "rotation breaks reading order: the room line is lost and a room is guessed"},
        "poster_khmer.png": {"variant": "khmer", "note": f"rendered {shaping}",
                             "truth": {"transcription": "\n".join(l for l in khmer_lines if l),
                                       "event": {**EVENT, "title": "CamTech AI Seminar"}},
                             "stub_reading": {"transcription": "CamTech AI Seminar\n16:00 - 17:30\nA-101",
                                              "event": {"title": "CamTech AI Seminar", "date": "2026-10-26",
                                                        "start": "16:00", "end": "17:30", "location": "A-101"}},
                             "failure": "Khmer digits and month name misread: the date is wrong"},
        "timetable_dense.png": {"variant": "dense_table",
                                "truth": {"transcription": "FECO303 lab Thursday 13:30 C-301",
                                          "event": {"title": "FECO303 lab", "date": None, "start": "13:30", "end": None,
                                                    "location": "C-301"}},
                                "stub_reading": {"transcription": "Week timetable FECO303 13:30 C-301 FESE311 C-301",
                                                 "event": {"title": "FECO303 lab", "date": None, "start": "13:30",
                                                           "end": None, "location": "D-101"}},
                                "failure": "dense table: rows and columns mixed up; the room comes from another row"},
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                       newline="\n")
    return manifest


if __name__ == "__main__":
    for name in build():
        print(f"wrote data/images/{name}")
    sys.exit(0)
