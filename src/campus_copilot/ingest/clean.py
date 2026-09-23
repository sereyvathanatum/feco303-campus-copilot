"""Stage 3, clean.

PDF: Unicode NFC; drop running headers and footers (lines repeated on at least half
of a document's pages, digits ignored) and page numbers; join words hyphenated
across line breaks; collapse whitespace.
Markdown: Unicode NFC; strip HTML comments; keep headings, lists, tables, and code;
compact padded table cells; restore the heading hierarchy of converter output where every
heading sits at one level ("## I. Programs", "## A. Undergraduate programs") from its numbering.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from . import tables

PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?\s*$", re.IGNORECASE)
HYPHEN_BREAK = re.compile(r"([a-z])-\n([a-z])")
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
NUMBERED = re.compile(r"^(?P<mark>[IVXLCDM]+|[A-Z]|\d+(?:\.\d+)*)\s?[.)]\s+\S")
ROMAN_VALUES = dict(zip("IVXLCDM", (1, 5, 10, 50, 100, 500, 1000)))


def _roman(mark: str) -> int | None:
    values = [ROMAN_VALUES.get(ch) for ch in mark]
    if not values or None in values:
        return None
    total = sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))
    return total if total > 0 else None


def relevel_headings(text: str) -> tuple[str, int]:
    """Rebuild heading levels from numbering when a document has no `#` title and one flat heading level.

    Roman numerals ("IV. Tuition Fees") become level 2, letters ("A) Bachelor's Degree") level 3,
    decimals ("2.1 Loans") one level per dot; an unnumbered heading goes under the last level-2 heading.
    Letters that are also Roman numerals (C, D, V) are told apart by sequence: "C)" after "B)" is a
    letter, "V." after "IV." is a numeral. Returns (text, headings changed).
    """
    lines = text.split("\n")
    found = [(i, m) for i, m in ((i, HEADING.match(line)) for i, line in enumerate(lines)) if m]
    levels = {len(m.group(1)) for _, m in found}
    numbered = [NUMBERED.match(m.group(2)) for _, m in found]
    if len(levels) != 1 or 1 in levels or sum(1 for n in numbered if n) < 2:
        return text, 0
    last_roman, last_letter, top_seen, changed = 0, 0, False, 0
    for (i, m), number in zip(found, numbered):
        title = m.group(2)
        level = 3 if top_seen else 2
        if number:
            mark = number.group("mark")
            roman = _roman(mark)
            letter_next = len(mark) == 1 and (mark == "A" or ord(mark) - 64 == last_letter + 1)
            if mark[0].isdigit():
                level = 2 + mark.count(".")
            elif roman is not None and roman == last_roman + 1 and not (letter_next and roman != 1):
                level, last_roman, last_letter, top_seen = 2, roman, 0, True
            elif len(mark) == 1:
                level, last_letter = 3, ord(mark) - 64
            elif roman is not None:
                level, last_roman, last_letter, top_seen = 2, roman, 0, True
        new = "#" * level + " " + title
        if new != lines[i]:
            lines[i], changed = new, changed + 1
    return "\n".join(lines), changed


def _line_key(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def clean_pdf_document(pages: list[dict], strip_headers: bool = True) -> list[dict]:
    keys_per_page = [{_line_key(l) for l in p["text"].splitlines() if l.strip()} for p in pages]
    counts = Counter(k for keys in keys_per_page for k in keys)
    threshold = max(2, (len(pages) + 1) // 2)
    repeated = {k for k, n in counts.items() if n >= threshold} if strip_headers and len(pages) >= 3 else set()
    out = []
    for page in pages:
        text = unicodedata.normalize("NFC", page["text"])
        removed = {"headers_footers": 0, "page_numbers": 0, "hyphen_joins": 0,
                   "control_chars": len(CONTROL.findall(text))}
        text = CONTROL.sub("", text)
        samples: list[str] = []
        kept_lines = []
        for line in text.splitlines():
            if strip_headers and PAGE_NUMBER.match(line):
                removed["page_numbers"] += 1
                samples.append(line.strip())
                continue
            if _line_key(line) in repeated and line.strip():
                removed["headers_footers"] += 1
                samples.append(line.strip())
                continue
            kept_lines.append(line.rstrip())
        body = "\n".join(kept_lines)
        removed["hyphen_joins"] = len(HYPHEN_BREAK.findall(body))
        body = HYPHEN_BREAK.sub(r"\1\2", body)
        body = re.sub(r"[ \t]+", " ", body)
        body = re.sub(r"\n{3,}", "\n\n", body).strip()
        out.append({"source_id": page["source_id"], "format": "pdf", "page": page["page"], "section": None,
                    "text": body, "script": page.get("script"), "chars_before": len(page["text"]),
                    "chars_after": len(body), "removed": removed, "samples": sorted(set(samples))[:6]})
    return out


def clean_markdown(unit: dict) -> dict:
    text = unicodedata.normalize("NFC", unit["text"])
    comments = HTML_COMMENT.findall(text)
    body = HTML_COMMENT.sub("", text)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    body, table_count = tables.compact(body)
    body, relevelled = relevel_headings(body)
    return {"source_id": unit["source_id"], "format": "md", "page": None, "section": None, "text": body,
            "script": unit.get("script"), "metadata": unit.get("metadata", {}),
            "chars_before": len(unit["text"]), "chars_after": len(body),
            "removed": {"html_comments": len(comments)},
            "repaired": {"tables_compacted": table_count, "headings_relevelled": relevelled},
            "samples": [c[:60] for c in comments[:3]]}


def clean(units: list[dict], strip_headers: bool = True) -> tuple[list[dict], dict]:
    out: list[dict] = []
    by_doc: dict[str, list[dict]] = {}
    for unit in units:
        if unit["format"] == "pdf":
            by_doc.setdefault(unit["source_id"], []).append(unit)
        else:
            out.append(clean_markdown(unit))
    for pages in by_doc.values():
        out.extend(clean_pdf_document(sorted(pages, key=lambda p: p["page"]), strip_headers))
    out.sort(key=lambda u: (u["source_id"], u["page"] or 0))
    totals: Counter = Counter()
    repaired: Counter = Counter()
    for u in out:
        totals.update(u["removed"])
        repaired.update(u.get("repaired", {}))
    stats = {"units": len(out), "removed": dict(totals), "repaired": dict(repaired),
             "chars_before": sum(u["chars_before"] for u in out), "chars_after": sum(u["chars_after"] for u in out),
             "strip_headers": strip_headers}
    return out, stats
