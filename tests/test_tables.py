"""Converter-style Markdown: table repair and row-wise splitting, heading levels, context headers (offline)."""

from __future__ import annotations

from campus_copilot import config
from campus_copilot.ingest import chunk as chunk_mod
from campus_copilot.ingest import clean, tables

# The shape a PDF-to-Markdown converter writes: flat `##` headings, padded cells, a two-row header,
# group-label rows, two tables with no blank line between them, and a table cut at a page break.
CONVERTED = """<!-- image -->

## I. Programs

Programs run on two levels.

## A. Undergraduate programs

|   No. | Majors                 | Level             |
|-------|------------------------|-------------------|
|     1 | Robotics               | Bachelor's Degree |
|     2 | Software Engineering   | Bachelor's Degree |

## II. Tuition Fees

Fees vary by major. See the fees below:

## A) Bachelor's Degree

| No.   | Majors of Study        | Fees/ Term   | Fees/ Term   | Tuition   |
|-------|------------------------|--------------|--------------|-----------|
| No.   | Majors of Study        | Term I       | Term II      | Fee/year  |
| 1     | Cyber Security         | $1,350       | $1,350       | $4,000    |
| 2     | Software Engineering   | $1,350       | $1,350       | $4,000    |
|   3 | Architecture |
|-----|--------------|
|   4 | Interior Design |

## B) Master's Degree

- Bachelor's degree or an equivalent certificate
- A letter of motivation and an updated CV

## C) Doctoral Degree

| No. | Type | Slots |
|-----|------|-------|
| 1. Women in STEM (43 slots) | 1. Women in STEM (43 slots) | 1. Women in STEM (43 slots) |
| 1   | 100% | 10 |

## III. Scholarships

| 2. Regional Equity (43 slots) | 2. Regional Equity (43 slots) | 2. Regional Equity (43 slots) |
|-------------------------------|-------------------------------|-------------------------------|
| 1 | 100% | 10 |
"""

DOC = {"source_id": "converted", "file": "x.md", "format": "md", "title": "Academic Info", "language": "en",
       "status": "new"}


def _chunks(**overrides):
    unit = {"source_id": "converted", "format": "md", "page": None, "text": CONVERTED}
    cleaned, stats = clean.clean([unit])
    profile = config.load_profile("offline")
    for key, value in overrides.items():
        section, _, name = key.partition(".")
        profile.data.setdefault(section, {})[name] = value
    chunks, _ = chunk_mod.chunk(cleaned, [DOC], profile, "builtin")
    return chunks, stats


def test_clean_compacts_tables_and_restores_heading_levels():
    text, _ = tables.compact("| a   |  b |\n|-----|----|\n|  1  | 2  |")
    assert text == "| a | b |\n|---|---|\n| 1 | 2 |"
    releveled, changed = clean.relevel_headings(
        "## I. Programs\n## A. Undergraduate\n## B. Graduate\n## II. Fees\n## A) Bachelor\n## C) Doctoral\n"
        "## D) Other\n## III. Three\n## Contact")
    assert changed == 6
    levels = [line.split(" ", 1)[0] for line in releveled.splitlines()]
    assert levels == ["##", "###", "###", "##", "###", "###", "###", "##", "###"], releveled


def test_relevel_leaves_documents_with_a_title_alone():
    text = "# Handbook\n## Loans\n## Fines"
    assert clean.relevel_headings(text) == (text, 0)


def test_table_repairs():
    blocks = tables.find_blocks(clean.clean([{"source_id": "c", "format": "md", "text": CONVERTED}])[0][0]["text"])
    found = [b for kind, b in blocks if kind == "table"]
    assert len(found) == 5, "two tables with no blank line between them are two tables"
    fees, continued = found[1], found[2]
    assert fees.header == ["No.", "Majors of Study", "Fees/ Term (Term I)", "Fees/ Term (Term II)", "Tuition Fee/year"]
    assert continued.header == ["No.", "Majors of Study"] and continued.rows[0].cells == ["3", "Architecture"]
    groups = found[3]
    assert groups.rows[0].group and groups.rows[0].label == "1. Women in STEM (43 slots)"
    cut = found[4]
    assert cut.header == ["No.", "Type", "Slots"], "a table cut at a page break takes the header before the cut"


def test_every_table_piece_repeats_the_header_and_never_splits_a_row():
    chunks, _ = _chunks(**{"rag.chunk_size": 60, "rag.chunk_overlap": 0})
    table_chunks = [c for c in chunks if "| Cyber Security |" in c["text"] or "| Software Engineering | $" in c["text"]]
    assert len(table_chunks) >= 2
    for c in table_chunks:
        assert "| No. | Majors of Study | Fees/ Term (Term I) |" in c["text"]
    for c in chunks:
        for line in c["text"].splitlines():
            if line.startswith("|"):
                assert line.endswith("|"), f"row cut in half: {line!r}"


def test_rows_format_writes_one_record_per_row():
    chunks, _ = _chunks(**{"ingest.tables": "rows"})
    text = "\n".join(c["text"] for c in chunks)
    assert "- No.: 1; Majors of Study: Cyber Security; Fees/ Term (Term I): $1,350" in text
    assert "**1. Women in STEM (43 slots)**" in text


def test_context_header_names_the_full_section_path():
    chunks, _ = _chunks()
    fees = next(c for c in chunks if "Cyber Security" in c["text"])
    assert fees["section"] == "II. Tuition Fees › A) Bachelor's Degree"
    assert fees["text"].startswith("# Academic Info › II. Tuition Fees › A) Bachelor's Degree\n")
    assert "## A) Bachelor's Degree" not in fees["text"], "the heading the breadcrumb repeats is dropped"
    plain, _ = _chunks(**{"ingest.context_header": "off"})
    assert not any(c["text"].startswith("# Academic Info") for c in plain)


def test_list_items_keep_their_marker_across_a_split():
    profile = config.load_profile("offline")
    profile.data.setdefault("rag", {}).update(chunk_size=24, chunk_overlap=0)
    sizing, _ = chunk_mod.counters(profile, "builtin")
    items = "\n".join(f"- Requirement number {n} needs a certified copy of the original document" for n in range(6))
    pieces = chunk_mod._splitter(profile, sizing).split_text(items)
    assert len(pieces) > 1
    for piece in pieces:
        assert not piece.rstrip().endswith("\n-") and piece.strip() != "-", "a list marker dangles"
        assert all(line.startswith("- ") for line in piece.strip().splitlines()), piece
