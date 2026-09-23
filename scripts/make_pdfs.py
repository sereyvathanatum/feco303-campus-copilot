"""Build data/sources/campus-handbook.pdf from data/sources/_src/campus-handbook.md.

Maintenance only (`pip install -r requirements-maint.txt`). The PDF gets a running
header and a footer with page numbers on every page, so the clean stage has real
headers, footers, and page numbers to remove. The Khmer page uses Noto Sans Khmer
(SIL Open Font License, data/sources/_src/fonts/) with HarfBuzz text shaping.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "sources" / "_src" / "campus-handbook.md"
OUT = ROOT / "data" / "sources" / "campus-handbook.pdf"
KHMER_FONT = ROOT / "data" / "sources" / "_src" / "fonts" / "NotoSansKhmer-Regular.ttf"
HEADER = "CamTech Campus Handbook 2026-2027 (demo edition)"
FOOTER = "Illustrative text for a demo system; not official CamTech policy."
KHMER = re.compile(r"[ក-៿]")


class Handbook(FPDF):
    total_pages = 0

    def header(self):
        self.set_font("Helvetica", "i", 8)
        self.set_text_color(110)
        self.cell(0, 6, HEADER, align="C")
        self.ln(10)

    def footer(self):
        self.set_y(-14)
        self.set_font("Helvetica", "i", 8)
        self.set_text_color(110)
        self.cell(0, 5, FOOTER, align="C")
        self.ln(4)
        self.cell(0, 5, f"Page {self.page_no()} of {self.total_pages}", align="C")


def split_pages(text: str) -> list[str]:
    text = re.sub(r"<!--(?!\s*page\s*-->).*?-->", "", text, flags=re.DOTALL)
    return [p.strip() for p in re.split(r"<!--\s*page\s*-->", text) if p.strip()]


def blocks(page: str) -> list[tuple[str, str]]:
    """Split one page into (kind, text) blocks: heading, item, or paragraph.

    Lines inside a paragraph are joined with spaces, except a line that ends in
    "-", which keeps its line break (a hyphenated break for the clean stage).
    """
    out: list[tuple[str, str]] = []
    para: list[str] = []

    def flush():
        if para:
            text = ""
            for line in para:
                text += line + ("\n" if line.endswith("-") else " ")
            out.append(("para", text.strip()))
            para.clear()

    for raw in page.splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith("# "):
            flush()
            out.append(("heading", line[2:]))
        elif line.startswith("- ") or re.match(r"^\d+\.\s", line):
            flush()
            out.append(("item", line))
        else:
            para.append(line)
    flush()
    return out


def build() -> Path:
    pages = split_pages(SRC.read_text(encoding="utf-8"))
    pdf = Handbook(format="A4")
    pdf.total_pages = len(pages)
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(22, 18, 22)
    has_khmer_font = KHMER_FONT.is_file()
    if has_khmer_font:
        pdf.add_font("NotoKhmer", "", str(KHMER_FONT))
        try:
            pdf.set_text_shaping(True)
        except Exception as exc:  # uharfbuzz missing: Khmer glyphs render unshaped
            print(f"warning: text shaping unavailable ({exc}); Khmer text is not shaped")
    for page in pages:
        pdf.add_page()
        khmer_page = bool(KHMER.search(page))
        if khmer_page and not has_khmer_font:
            print("warning: Khmer font missing; the Khmer page is skipped")
            continue
        for kind, text in blocks(page):
            pdf.set_text_color(0)
            if khmer_page:
                pdf.set_font("NotoKhmer", size=15 if kind == "heading" else 11)
            elif kind == "heading":
                pdf.set_font("Helvetica", "B", 15)
            else:
                pdf.set_font("Helvetica", size=11)
            height = 8 if kind == "heading" else 6
            if kind == "item":
                pdf.set_x(pdf.l_margin + 4)
                pdf.multi_cell(0, height, text, new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.multi_cell(0, height, text, new_x="LMARGIN", new_y="NEXT")
                pdf.ln(3)
    pdf.set_title("CamTech Campus Handbook 2026-2027 (demo edition)")
    pdf.set_author("feco303-campus-copilot")
    pdf.set_creation_date(__import__("datetime").datetime(2026, 9, 23))
    pdf.output(str(OUT))
    return OUT


FIXTURES = ROOT / "tests" / "fixtures" / "ingest"


class FixturePdf(FPDF):
    total_pages = 0

    def header(self):
        self.set_font("Helvetica", "i", 8)
        self.cell(0, 6, "Fixture Rules Booklet (test data)", align="C")
        self.ln(10)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "i", 8)
        self.cell(0, 5, f"Page {self.page_no()} of {self.total_pages}", align="C")


def _fixture(path: Path, pages: list[list[str]]) -> None:
    pdf = FixturePdf(format="A5")
    pdf.total_pages = len(pages)
    pdf.set_auto_page_break(auto=True, margin=16)
    for lines in pages:
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        for line in lines:
            pdf.multi_cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
    pdf.set_creation_date(__import__("datetime").datetime(2026, 9, 23))
    pdf.output(str(path))


def build_fixtures() -> list[Path]:
    """Two small PDFs for the ingestion tests: running header, page numbers, a hyphen break, a near-empty page."""
    FIXTURES.mkdir(parents=True, exist_ok=True)
    rules = FIXTURES / "fixture-rules.pdf"
    _fixture(rules, [
        ["Bicycle parking", "Bicycles are parked in the rack behind Building D. A rack space needs a yearly regis-\n"
         "tration sticker from the Security desk."],
        ["Locker rental", "Lockers in Building B are rented per semester for 4 US dollars. Keys are returned in the "
         "last week of the semester."],
        ["Lost keys", "A lost locker key costs 2 US dollars to replace. The Security desk opens lockers after an "
         "identity check."],
    ])
    sparse = FIXTURES / "fixture-sparse.pdf"
    _fixture(sparse, [["Quiet hours", "Quiet hours in the study hall run from 20:00 to 07:00 every day."], [], ["End."]])
    return [rules, sparse]


if __name__ == "__main__":
    if "--fixtures" in sys.argv:
        for path in build_fixtures():
            print(f"wrote {path.relative_to(ROOT)}")
        sys.exit(0)
    path = build()
    print(f"wrote {path.relative_to(ROOT)}")
    sys.exit(0)
