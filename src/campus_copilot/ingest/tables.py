"""Markdown tables: find, repair converter artefacts, render, and split by whole rows.

PDF-to-Markdown converters (docling, marker, pandoc) write tables with padded cells, a second
header row for merged column groups, group-label rows that repeat one text across every cell,
and tables cut in two at a page break. A plain recursive splitter treats such a table as prose:
it cuts rows at ". " (so "No." breaks off the header), splits rows in half, and leaves the
continuation chunks without a header row, so a model reads "$1,350 | $4,000" with no column names.

Here a table is split only between rows, and every piece repeats the header row and the current
group label, so each chunk stands alone (`ingest.tables`):

* `markdown`: compact Markdown table per piece (default)
* `rows`: one "Column: value; Column: value" line per row, for embedders that read prose better
* `text`: no table handling (the plain splitter; for comparison in E02)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

ROW = re.compile(r"^\s*\|.*\|\s*$")
SEPARATOR_CELL = re.compile(r"^:?-+:?$")
PIPE = re.compile(r"(?<!\\)\|")
DIGIT = re.compile(r"\d")
INTEGER = re.compile(r"^\d{1,4}\.?$")
FORMATS = ("markdown", "rows", "text")


@dataclass
class Row:
    cells: list[str]
    group: bool = False  # a group label spanning the whole row, e.g. "1. Women in STEM Scholarships (43 slots)"

    @property
    def label(self) -> str:
        return next((c for c in self.cells if c), "")


@dataclass
class Table:
    header: list[str] | None
    rows: list[Row] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)

    @property
    def width(self) -> int:
        return max([len(self.header or [])] + [len(r.cells) for r in self.rows if not r.group] or [0])


def split_cells(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") else body
    return [c.strip() for c in PIPE.split(body)]


def is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(SEPARATOR_CELL.match(c.replace(" ", "")) for c in cells)


def _is_group(cells: list[str]) -> bool:
    filled = [c for c in cells if c]
    return len(cells) > 1 and len(filled) >= 2 and len(set(filled)) == 1


def _spans(header: list[str]) -> bool:
    return any(a and a == b for a, b in zip(header, header[1:])) or any(not h for h in header)


def _is_second_header(header: list[str], cells: list[str]) -> bool:
    """The converter's second header row: a merged column group above, the real column names below."""
    if not cells or _is_group(cells):
        return False
    if cells[0] and cells[0] == header[0]:
        return True
    return _spans(header) and not any(DIGIT.search(c) for c in cells)


def _merge_header(first: list[str], second: list[str]) -> list[str]:
    merged = []
    for i in range(max(len(first), len(second))):
        a = first[i] if i < len(first) else ""
        b = second[i] if i < len(second) else ""
        spanned = bool(a) and ((i > 0 and first[i - 1] == a) or (i + 1 < len(first) and first[i + 1] == a))
        if not b or a == b:
            merged.append(a)
        elif not a:
            merged.append(b)
        elif spanned:
            merged.append(f"{a} ({b})")  # "Tuition Fees/ Term (Term I)"
        else:
            merged.append(f"{a} {b}")  # a label wrapped over two rows: "Tuition" + "Fee/year"
    return merged


def parse(lines: list[str], previous: Table | None = None) -> Table:
    header = split_cells(lines[0])
    body = [cells for cells in (split_cells(line) for line in lines[2:]) if not is_separator(cells)]
    table = Table(header=header)
    if _is_group(header):
        # A header that is one repeated label: the table continues a table cut at a page break.
        table.rows.append(Row(header, group=True))
        table.header = None
        table.repairs.append("group-label header")
    elif header and INTEGER.match(header[0]) and previous is not None and previous.header:
        # A header that is a numbered data row: the continuation of the previous table.
        table.rows.append(Row(header))
        table.header = None
        table.repairs.append("data row as header")
    if table.header and body and _is_second_header(table.header, body[0]):
        table.header = _merge_header(table.header, body.pop(0))
        table.repairs.append("two-row header merged")
    for cells in body:
        table.rows.append(Row(cells, group=_is_group(cells)))
    if sum(r.group for r in table.rows):
        table.repairs.append(f"{sum(r.group for r in table.rows)} group-label rows")
    if table.header is None and previous is not None and previous.header:
        width = table.width
        if width <= len(previous.header):
            table.header = previous.header[:width]
            table.repairs.append("header taken from the previous table")
    return table


def _starts_table(lines: list[str], i: int) -> bool:
    return (ROW.match(lines[i]) is not None and i + 1 < len(lines) and ROW.match(lines[i + 1]) is not None
            and is_separator(split_cells(lines[i + 1])))


def find_blocks(text: str, previous: Table | None = None) -> list[tuple[str, str | Table]]:
    """Split text into ("text", str) and ("table", Table) blocks, in order.

    `previous`: the last table seen earlier in the same document, for tables cut at a page break.
    """
    lines = text.split("\n")
    blocks: list[tuple[str, str | Table]] = []
    buffer: list[str] = []
    i = 0
    while i < len(lines):
        if _starts_table(lines, i):
            if "\n".join(buffer).strip():
                blocks.append(("text", "\n".join(buffer)))
            buffer = []
            j = i + 2
            # a header row with its own separator starts the next table, even with no blank line between
            while j < len(lines) and ROW.match(lines[j]) and not _starts_table(lines, j):
                j += 1
            previous = parse(lines[i:j], previous)
            blocks.append(("table", previous))
            i = j
        else:
            buffer.append(lines[i])
            i += 1
    if "\n".join(buffer).strip():
        blocks.append(("text", "\n".join(buffer)))
    return blocks


def compact(text: str) -> tuple[str, int]:
    """Strip cell padding and shorten separator rows; returns (text, tables compacted)."""
    out, count, in_table = [], 0, False
    for line in text.split("\n"):
        if ROW.match(line):
            cells = split_cells(line)
            if is_separator(cells):
                out.append("|" + "|".join("---" for _ in cells) + "|")
                count += 0 if in_table else 1
                in_table = True
            else:
                out.append("| " + " | ".join(cells) + " |")
        else:
            out.append(line)
            in_table = False
    return "\n".join(out), count


# ------------------------------------------------------------------ rendering

def _md_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def header_lines(table: Table, fmt: str) -> list[str]:
    if fmt != "markdown" or not table.header:
        return []
    return [_md_row(table.header), "|" + "|".join("---" for _ in table.header) + "|"]


def render_row(table: Table, row: Row, fmt: str) -> str:
    if row.group:
        return f"**{row.label}**" if fmt == "rows" else _md_row([f"**{row.label}**"] + [""] * (table.width - 1))
    if fmt == "markdown":
        return _md_row(row.cells)
    names = table.header or [f"Column {i + 1}" for i in range(len(row.cells))]
    pairs = [f"{names[i] if i < len(names) and names[i] else f'Column {i + 1}'}: {value}"
             for i, value in enumerate(row.cells) if value]
    return "- " + "; ".join(pairs)


def render(table: Table, fmt: str = "markdown") -> str:
    return "\n".join(header_lines(table, fmt) + [render_row(table, r, fmt) for r in table.rows])


def pieces(table: Table, budget: int, count: Callable[[str], int], fmt: str = "markdown") -> list[str]:
    """Split a table between rows so each piece fits `budget`; every piece repeats the header and group label."""
    head = header_lines(table, fmt)
    out: list[str] = []
    current: list[str] = []
    group: str | None = None
    for row in table.rows:
        line = render_row(table, row, fmt)
        if current and count("\n".join(head + current + [line])) > budget:
            out.append("\n".join(head + current))
            current = [group] if group and not row.group else []
        if row.group:
            group = line
        current.append(line)
    if current:
        out.append("\n".join(head + current))
    return out
